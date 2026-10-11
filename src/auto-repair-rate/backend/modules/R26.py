"""R26 target gap monitor. Server-side calculations with auditable evidence."""
from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus

MODULE_ID = "R26"
router = APIRouter(tags=["R26 target gap and candidate"])

class Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    source_date: date
    effective_from: date
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    actual_labor_revenue_yen: float | None = Field(default=None, ge=0)
    target_revenue_yen: float | None = Field(default=None, ge=0)
    billed_hours: float | None = Field(default=None, ge=0)
    allocable_cost_yen: float | None = Field(default=None, ge=0)


def _result(body: Input):
    blockers: list[str] = []
    basis: list[BasisRow] = []
    candidate = None
    denominator = None
    vals=[body.actual_labor_revenue_yen,body.target_revenue_yen,body.billed_hours,body.allocable_cost_yen]
    if any(v is None for v in vals): blockers.append("実績売上・目標・請求人時・費用が必要です")
    elif body.billed_hours<=0: blockers.append("請求人時が0です")
    else:
        gap=body.target_revenue_yen-body.actual_labor_revenue_yen
        required=body.target_revenue_yen/body.billed_hours
        basis += [BasisRow(label="目標売上差",value=gap,unit="円"),BasisRow(label="目標達成に必要な参考単価",value=required,unit="円/人時"),BasisRow(label="実績単価だけで自動変更しない",value=True,unit="review")]
        candidate=required; denominator=body.billed_hours
    basis += [BasisRow(label="実際の工賃売上",value=body.actual_labor_revenue_yen,unit="円"),BasisRow(label="目標",value=body.target_revenue_yen,unit="円"),BasisRow(label="配賦費用",value=body.allocable_cost_yen,unit="円")]
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
    return store.create_proposal(proposal, module_calculation=calc, rate_scope="factory_standard", rate_type="customer")

@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "module proposal not found")
    return store.get_proposal(proposal_id)
