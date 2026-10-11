"""R18 incomplete expense range with explicit uncertainty acceptance."""
from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r18_incomplete_costs import calculate_incomplete_costs

MODULE_ID = "R18"
router = APIRouter(tags=["R18 provisional incomplete-cost range"])
class UnknownCost(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1)
    lower_yen: float | None = Field(default=None, ge=0)
    upper_yen: float | None = Field(default=None, ge=0)
    source: str = Field(min_length=1)
    @model_validator(mode="after")
    def ordered(self):
        if self.lower_yen is not None and self.upper_yen is not None and self.lower_yen > self.upper_yen: raise ValueError("費用幅は下限 <= 上限にしてください")
        return self
class R18Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    known_cost_yen: float | None = Field(default=None, ge=0)
    unknown_items: list[UnknownCost] = Field(default_factory=list)
    H_period_bill: float | None = Field(default=None, ge=0)
    accept_uncertainty: bool = False
    materials_excluded: bool = False
    period_start: str = Field(min_length=10); period_end: str = Field(min_length=10); effective_from: str = Field(min_length=10)
    source: str = Field(min_length=1); source_date: str = Field(min_length=10); evidence_ref: str = Field(min_length=1); evidence_notes: str = Field(min_length=1)
def _calc(body): return calculate_incomplete_costs(body.known_cost_yen, [x.model_dump() for x in body.unknown_items], body.H_period_bill, body.accept_uncertainty, body.materials_excluded)
@router.post("/rates/preview")
def preview(body: R18Input): return _calc(body)
@router.post("/proposals")
def create_proposal(body: R18Input):
    result = _calc(body); now = datetime.now(timezone.utc)
    evidence = [Evidence(label="確認済み費用と不明費用の範囲", value=body.evidence_notes, unit="説明", status="assumed" if body.unknown_items or "架空" in body.source else "factory_reported", source=body.source, evidence_ref=body.evidence_ref, recorded_at=now, notes=f"資料日={body.source_date}; 不確実性の明示的受け入れ={body.accept_uncertainty}; 別請求材料除外={body.materials_excluded}")]
    from backend.models import CostItem
    excluded = []
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, period_end=body.period_end, effective_from=body.effective_from, allocable_cost_yen=result.get("lower_cost_yen", body.known_cost_yen), period_total_person_hours=body.H_period_bill, u_period=1 if body.H_period_bill is not None else None, costs=excluded, evidence=evidence, source=body.source, notes="不明費用は0扱いせず、候補は入力範囲に基づく暫定値")
    basis = [BasisRow(label="確認済み費用による下限", value=result.get("known_lower_bound"), unit="円/人時"), BasisRow(label="承認した費用範囲の単価下限", value=result.get("lower_candidate"), unit="円/人時"), BasisRow(label="承認した費用範囲の単価上限", value=result.get("upper_candidate"), unit="円/人時"), BasisRow(label="請求可能人時", value=body.H_period_bill, unit="人時/期間"), BasisRow(label="不確実性受け入れ", value=body.accept_uncertainty, unit="確認"), BasisRow(label="別請求材料の除外確認", value=body.materials_excluded, unit="確認"), BasisRow(label="不明費用と根拠", value="; ".join(f"{x.label}: {x.lower_yen}〜{x.upper_yen}円 ({x.source})" for x in body.unknown_items) or "不明費用なし", unit="range"), BasisRow(label="根拠資料日・参照", value=f"{body.source_date} / {body.evidence_ref}", unit="source_ref")]
    blockers = result["blockers"]
    calc = RateCalculation(status=RateStatus.blocked if blockers else RateStatus.draft, candidate_yen_per_person_hour=result.get("lower_candidate"), denominator_person_hours=body.H_period_bill, u_period=1 if body.H_period_bill is not None else None, unknowns=blockers, basis=basis)
    return store.create_proposal(proposal, module_calculation=calc)
