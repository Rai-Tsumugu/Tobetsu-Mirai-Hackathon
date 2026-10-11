"""R17 side-by-side paid-wage and imputed-family-labor candidates."""
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter
from pydantic import ConfigDict, Field
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r17_family_labor import calculate_family_labor

MODULE_ID = "R17"
router = APIRouter(tags=["R17 paid and family labor comparison"])
class R17Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    paid_wages_yen: float | None = Field(default=None, ge=0)
    family_hours: float | None = Field(default=None, ge=0)
    shadow_cost_rate_yen: float | None = Field(default=None, ge=0)
    H_period_bill: float | None = Field(default=None, ge=0)
    selected_basis: Literal["paid_only", "with_family"]
    period_start: str = Field(min_length=10); period_end: str = Field(min_length=10); effective_from: str = Field(min_length=10)
    source: str = Field(min_length=1); source_date: str = Field(min_length=10); evidence_ref: str = Field(min_length=1); evidence_notes: str = Field(min_length=1)
def _calc(body): return calculate_family_labor(body.paid_wages_yen, body.family_hours, body.shadow_cost_rate_yen, body.H_period_bill)
@router.post("/rates/preview")
def preview(body: R17Input):
    result = _calc(body); field = "paid_only_yen_per_person_hour" if body.selected_basis == "paid_only" else "with_family_yen_per_person_hour"
    blockers = result["blockers"][:]
    if body.selected_basis == "with_family" and result["family_shadow_cost_yen"] is None: blockers.append("家族労務仮原価の前提が必要です")
    return {**result, "selected_candidate_yen_per_person_hour": None if blockers else result[field], "selected_basis": body.selected_basis, "blockers": blockers}
@router.post("/proposals")
def create_proposal(body: R17Input):
    result = preview(body); now = datetime.now(timezone.utc)
    evidence = [Evidence(label="給与と家族労務の根拠", value=body.evidence_notes, unit="説明", status="assumed" if "架空" in body.source else "factory_reported", source=body.source, evidence_ref=body.evidence_ref, recorded_at=now, notes=f"資料日={body.source_date}; 仮原価は税務・給与処理上の助言ではありません")]
    paid = result["paid_only_yen_per_person_hour"]; with_family = result["with_family_yen_per_person_hour"]
    selected = result["selected_candidate_yen_per_person_hour"]
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, period_end=body.period_end, effective_from=body.effective_from, allocable_cost_yen=body.paid_wages_yen, period_total_person_hours=body.H_period_bill, u_period=1 if body.H_period_bill is not None else None, evidence=evidence, source=body.source, notes=f"selected_basis={body.selected_basis}; family labor imputation is a separate assumption")
    basis = [BasisRow(label="実支払給与候補", value=paid, unit="円/人時"), BasisRow(label="家族労務の仮原価", value=result["family_shadow_cost_yen"], unit="円/期間"), BasisRow(label="家族労務込み候補", value=with_family, unit="円/人時"), BasisRow(label="選択された候補基準", value=body.selected_basis, unit="basis"), BasisRow(label="請求可能人時", value=body.H_period_bill, unit="人時/期間"), BasisRow(label="仮原価率", value=body.shadow_cost_rate_yen, unit="円/人時"), BasisRow(label="根拠資料日・参照", value=f"{body.source_date} / {body.evidence_ref}", unit="source_ref")]
    calc = RateCalculation(status=RateStatus.blocked if result["blockers"] else RateStatus.draft, candidate_yen_per_person_hour=selected, denominator_person_hours=body.H_period_bill, u_period=1 if body.H_period_bill is not None else None, unknowns=result["blockers"], basis=basis)
    return store.create_proposal(proposal, module_calculation=calc)
