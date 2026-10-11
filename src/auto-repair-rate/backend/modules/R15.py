"""R15 annual aggregate-cost quick entry."""
from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import ConfigDict, Field
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r15_annual_summary import calculate_annual_summary

MODULE_ID = "R15"
router = APIRouter(tags=["R15 annual summary rate"])

class R15Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    allocable_cost_yen: float | None = Field(default=None, ge=0)
    H_period_total: float | None = Field(default=None, ge=0)
    u_period: float | None = Field(default=None, ge=0, le=1)
    materials_excluded: bool = False
    period_start: str = Field(min_length=10)
    period_end: str = Field(min_length=10)
    effective_from: str = Field(min_length=10)
    source: str = Field(min_length=1)
    source_date: str = Field(min_length=10)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)

def _calc(body):
    return calculate_annual_summary(body.allocable_cost_yen, body.H_period_total, body.u_period, body.materials_excluded)

@router.post("/rates/preview")
def preview(body: R15Input): return _calc(body)

@router.post("/proposals")
def create_proposal(body: R15Input):
    result = _calc(body); now = datetime.now(timezone.utc)
    evidence = [Evidence(label="年次合算額と入力根拠", value=body.evidence_notes, unit="説明", status="assumed" if "架空" in body.source else "factory_reported", source=body.source, evidence_ref=body.evidence_ref, recorded_at=now, notes=f"資料日={body.source_date}; 材料除外確認={body.materials_excluded}; 内訳未確認の場合は合算申告")]
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, period_end=body.period_end, effective_from=body.effective_from,
        allocable_cost_yen=body.allocable_cost_yen, period_total_person_hours=body.H_period_total, u_period=body.u_period,
        evidence=evidence, source=body.source, notes="年額合算。費目内訳は別途確認が必要")
    basis = [BasisRow(label="配賦費用合計", value=body.allocable_cost_yen, unit="円/期間"), BasisRow(label="期間総労働人時", value=body.H_period_total, unit="人時/期間"), BasisRow(label="u_period", value=body.u_period, unit="割合"), BasisRow(label="別請求材料の除外確認", value=body.materials_excluded, unit="確認"), BasisRow(label="根拠資料日・参照", value=f"{body.source_date} / {body.evidence_ref}", unit="source_ref")]
    calc = RateCalculation(status=RateStatus.blocked if result["blockers"] else RateStatus.draft, candidate_yen_per_person_hour=result["candidate_yen_per_person_hour"], denominator_person_hours=result["denominator_person_hours"], u_period=body.u_period, unknowns=result["blockers"], basis=basis)
    return store.create_proposal(proposal, module_calculation=calc)
