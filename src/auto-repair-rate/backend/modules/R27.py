"""R27 cost waterfall. Server-side calculations with auditable evidence."""
from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus

MODULE_ID = "R27"
router = APIRouter(tags=["R27 cost contributions"])

class CostItem(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1)
    amount_yen: float | None = Field(default=None, ge=0)
    included_in_labor_pool: bool = True
    billing_class: Literal["labor_pool", "separately_billed_item"] = "labor_pool"

class Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    source_date: date
    effective_from: date
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    cost_items: list[CostItem] = Field(min_length=1)
    billable_hours: float | None = Field(default=None, ge=0)
    profit_yen: float = Field(default=0, ge=0)
    target_rate_yen: float | None = Field(default=None, ge=0)


def _result(body: Input):
    blockers: list[str] = []
    basis: list[BasisRow] = []
    candidate = None
    denominator = None
    total=0.0
    for item in body.cost_items:
        amount=item.amount_yen; label=item.label; included=item.included_in_labor_pool; kind=item.billing_class
        if kind=="separately_billed_item": basis.append(BasisRow(label=f"{label}（別請求・除外）",value=amount,unit="円")); continue
        if not included: basis.append(BasisRow(label=f"{label}（別請求・除外）",value=amount,unit="円")); continue
        if amount is None: blockers.append(f"{label}: 金額が不明です"); continue
        total += float(amount)
    if body.billable_hours is None: blockers.append("請求可能人時が不明です")
    elif body.billable_hours<=0: blockers.append("請求可能人時が0です")
    elif not blockers:
        denominator=body.billable_hours; candidate=(total+body.profit_yen)/denominator
    for item in body.cost_items:
        amount=item.amount_yen; label=item.label; included=item.included_in_labor_pool and item.billing_class=="labor_pool"
        if included and amount is not None: basis.append(BasisRow(label=f"{label}の1人時寄与",value=float(amount)/body.billable_hours if body.billable_hours else None,unit="円/人時"))
    basis += [BasisRow(label="利益目標の寄与",value=body.profit_yen/body.billable_hours if body.billable_hours else None,unit="円/人時"),BasisRow(label="ウォーターフォール合計",value=candidate,unit="円/人時"),BasisRow(label="入力済み目標単価との一致",value=(None if body.target_rate_yen is None or candidate is None else abs(candidate-body.target_rate_yen)<0.01),unit="boolean"),BasisRow(label="材料費は別請求として除外",value=True,unit="policy")]
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
