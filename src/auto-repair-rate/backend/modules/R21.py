"""R21 category scoped customer rate. Server-side calculations with auditable evidence."""
from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus

MODULE_ID = "R21"
router = APIRouter(tags=["R21 category cost pools"])

class Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    source_date: date
    effective_from: date
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    category_id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    category_name: str = Field(min_length=1)
    direct_cost_yen: float | None = Field(default=None, ge=0)
    shared_cost_yen: float | None = Field(default=None, ge=0)
    allocation_share: float | None = Field(default=None, ge=0, le=1)
    billable_hours: float | None = Field(default=None, ge=0)
    materials_yen: float | None = Field(default=None, ge=0)


def _result(body: Input):
    blockers: list[str] = []
    basis: list[BasisRow] = []
    candidate = None
    denominator = None
    if body.direct_cost_yen is None or body.shared_cost_yen is None or body.allocation_share is None: blockers.append("カテゴリ費用と共通費配賦率が必要です")
    if body.billable_hours is None: blockers.append("カテゴリ請求可能人時が不明です")
    if body.billable_hours is not None and body.billable_hours <= 0: blockers.append("カテゴリ請求可能人時が0です")
    cost=(body.direct_cost_yen + body.shared_cost_yen*body.allocation_share) if body.direct_cost_yen is not None and body.shared_cost_yen is not None and body.allocation_share is not None else None
    if not blockers: candidate=cost/body.billable_hours; denominator=body.billable_hours
    basis += [BasisRow(label="カテゴリ",value=body.category_name,unit=body.category_id),BasisRow(label="直接費",value=body.direct_cost_yen,unit="円"),BasisRow(label="共通費の配賦額",value=(body.shared_cost_yen*body.allocation_share if body.shared_cost_yen is not None and body.allocation_share is not None else None),unit="円"),BasisRow(label="別請求材料費（除外）",value=body.materials_yen,unit="円"),BasisRow(label="カテゴリ請求可能人時",value=body.billable_hours,unit="人時")]
    return blockers, basis, candidate, denominator

@router.post("/rates/preview")
def preview(body: Input):
    blockers, basis, candidate, denominator = _result(body)
    return {"status": "blocked" if blockers else "draft", "candidate_yen_per_person_hour": candidate,
            "denominator_person_hours": denominator, "blockers": blockers,
            "basis": [row.model_dump() for row in basis]}

@router.post("/proposals")
def create_proposal(body: Input):
    blockers, basis, candidate, denominator = _result(body)
    now = datetime.now(timezone.utc)
    evidence = [Evidence(label="入力根拠", value=body.evidence_notes, unit="説明",
                         status="assumed" if "架空" in body.source else "factory_reported",
                         source=body.source, evidence_ref=body.evidence_ref, recorded_at=now,
                         notes=f"原資料日={body.source_date}")]
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, effective_from=body.effective_from,
                            allocable_cost_yen=(candidate * denominator if candidate is not None and denominator else None),
                            period_total_person_hours=denominator, u_period=1 if denominator else None,
                            evidence=evidence, source=body.source, notes="候補はサーバー側で算出。別請求材料費は含まない。")
    calc = RateCalculation(status=RateStatus.blocked if blockers else RateStatus.draft,
                           candidate_yen_per_person_hour=candidate if not blockers else None,
                           denominator_person_hours=denominator, u_period=1 if denominator else None,
                           unknowns=blockers, basis=basis)
    return store.create_proposal(proposal, module_calculation=calc, rate_scope=f"category:{body.category_id}", rate_type="customer")

@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "module proposal not found")
    return store.get_proposal(proposal_id)
