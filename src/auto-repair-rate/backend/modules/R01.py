"""R01 annual cost proposal endpoints backed by the shared append-only store."""
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field

from backend import store
from backend.models import ApprovalRequest, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r01_annual_cost import calculate_annual_cost

MODULE_ID = "R01"
router = APIRouter(tags=["R01 annual cost"])


class R01ProposalCreate(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    proposal: RateProposal
    payroll_overlap_cost_ids: list[str] = Field(default_factory=list)
    payroll_overlap_unconfirmed_cost_ids: list[str] = Field(default_factory=list)
    cost_evidence_by_id: dict[str, str] = Field(default_factory=dict)


def _require_r01(proposal: RateProposal) -> None:
    if proposal.module_id != MODULE_ID:
        raise HTTPException(422, "module_id must be R01")


def _require_stored_r01(proposal_id: str) -> None:
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "R01 proposal not found")


@router.post("/proposals")
def create_proposal(body: R01ProposalCreate):
    proposal = body.proposal
    _require_r01(proposal)
    evidence_by_label = {item.label: item for item in proposal.evidence}
    evidence_status = {
        "entered": "provided",
        "factory_reported": "confirmed",
        "assumed": "estimated",
        "unknown": "unknown",
        "terms_unverified": "unknown",
    }
    r01_result = calculate_annual_cost({
        "period_label": proposal.period_start.isoformat(),
        "period_start": proposal.period_start.isoformat(),
        "period_end": proposal.period_end.isoformat() if proposal.period_end else None,
        "effective_from": proposal.effective_from.isoformat(),
        "annual_allocable_cost_yen": proposal.allocable_cost_yen,
        "H_period_total": proposal.period_total_person_hours,
        "u_period": proposal.u_period,
        "hours_basis": proposal.hours_basis.value if proposal.hours_basis is not None else None,
        "job_billable_ratio": proposal.job_billable_ratio,
        "job_person_hours": proposal.job_person_hours.model_dump() if proposal.job_person_hours else None,
        "costs": [{
            "id": item.cost_id,
            "category": "materials" if item.billing_class == "separately_billed_item" else "labor",
            "label": item.label,
            "amount_yen": item.amount_yen,
            "included_in_rate": item.included_in_labor_pool,
            "status": evidence_status[item.evidence_status.value],
            "source": item.source,
            "evidence": body.cost_evidence_by_id.get(item.cost_id)
                or (evidence_by_label.get(item.label).notes if evidence_by_label.get(item.label) else None),
            "payroll_overlap": item.cost_id in body.payroll_overlap_cost_ids,
            "payroll_overlap_confirmed": item.cost_id not in body.payroll_overlap_unconfirmed_cost_ids,
        } for item in proposal.costs],
    })

    calculation = RateCalculation.model_validate(r01_result["shared_calculation"])
    blockers = r01_result["blockers"]
    if blockers:
        calculation.status = RateStatus.blocked
        calculation.candidate_yen_per_person_hour = None
        calculation.unknowns = sorted(set(calculation.unknowns + blockers))
        return store.create_proposal(proposal, module_calculation=calculation)

    local_candidate = float(r01_result["candidate_yen_per_person_hour"])
    shared_candidate = calculation.candidate_yen_per_person_hour
    if shared_candidate is None or abs(shared_candidate - local_candidate) > 1e-8:
        calculation.status = RateStatus.blocked
        calculation.candidate_yen_per_person_hour = None
        calculation.unknowns = sorted(set(calculation.unknowns + ["R01_and_shared_calculation_mismatch"]))
        return store.create_proposal(proposal, module_calculation=calculation)
    return store.create_proposal(proposal, module_calculation=calculation)


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    _require_stored_r01(proposal_id)
    return store.get_proposal(proposal_id)


@router.post("/proposals/{proposal_id}/approval")
def approve_proposal(proposal_id: str, body: ApprovalRequest):
    _require_stored_r01(proposal_id)
    try:
        return store.approve(proposal_id, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
