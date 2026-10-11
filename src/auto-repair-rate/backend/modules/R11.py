"""R11 seasonal scenarios; selection and shared approval remain explicit."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import ConfigDict, Field, model_validator

from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r11_seasonal_scenarios import calculate_seasonal_scenarios

MODULE_ID = "R11"
router = APIRouter(tags=["R11 seasonal scenarios"])


class Scenario(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["annual", "winter", "smoothed"]
    fixed_cost_yen: float | None = Field(default=None, ge=0)
    variable_cost_yen: float | None = Field(default=None, ge=0)
    H_period_bill: float | None = Field(default=None, ge=0)
    period: str = Field(min_length=1)
    assumptions: str = Field(min_length=1)


class R11Create(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    scenarios: list[Scenario] = Field(min_length=3, max_length=3)
    selected_scenario: Literal["annual", "winter", "smoothed"] | None = None
    period_start: str = Field(min_length=10)
    effective_from: str = Field(min_length=10)
    source: str = Field(min_length=1)
    source_date: str = Field(min_length=10)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    materials_yen: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_each_named_scenario(self):
        if {scenario.name for scenario in self.scenarios} != {"annual", "winter", "smoothed"}:
            raise ValueError("annual, winter, and smoothed scenarios are each required exactly once")
        return self


def _result(body: R11Create):
    return calculate_seasonal_scenarios([s.model_dump() for s in body.scenarios])


@router.post("/rates/preview")
def preview(body: R11Create):
    return _result(body)


@router.post("/proposals")
def create_proposal(body: R11Create):
    result = _result(body)
    chosen = next((item for item in result["scenarios"] if item["name"] == body.selected_scenario), None)
    blockers = [] if chosen and chosen["available"] else ["利用可能な単価シナリオを明示選択してください"]
    now = datetime.now(timezone.utc)
    basis = [BasisRow(label=f"{item['name']} シナリオ", value=item["basis"], unit="期間・仮定") for item in result["scenarios"]]
    if chosen:
        selected = next(s for s in body.scenarios if s.name == chosen["name"])
        basis += [BasisRow(label="選択シナリオ", value=chosen["name"], unit="scenario_id"),
                  BasisRow(label="選択シナリオの対象期間", value=selected.period, unit="period"),
                  BasisRow(label="選択シナリオの前提", value=selected.assumptions, unit="assumptions"),
                  BasisRow(label="固定費", value=selected.fixed_cost_yen, unit=f"円/{selected.period}"),
                  BasisRow(label="変動費", value=selected.variable_cost_yen, unit=f"円/{selected.period}"),
                  BasisRow(label="請求可能人時", value=selected.H_period_bill, unit=f"人時/{selected.period}")]
    basis += [BasisRow(label="適用単価", value="未適用", unit="人による選択・承認が必要"),
              BasisRow(label="原資料の日付", value=body.source_date, unit="日付"),
              BasisRow(label="根拠参照", value=body.evidence_ref, unit="source_ref")]
    from backend.models import CostItem
    excluded = [CostItem(cost_id="separately_billed_materials", label="別請求の部品・材料費", amount_yen=body.materials_yen,
                         period="入力期間", source=body.source, evidence_status="assumed" if "架空" in body.source else "entered",
                         billing_class="separately_billed_item", included_in_labor_pool=False)] if body.materials_yen is not None else []
    evidence = [Evidence(label="シナリオ条件", value=body.evidence_notes, unit="説明", status="assumed" if "架空" in body.source else "entered",
                         source=body.source, evidence_ref=body.evidence_ref, recorded_at=now, notes="各ケースは独立計算。候補の共有には人の選択が必要")]
    selected = next((s for s in body.scenarios if chosen and s.name == chosen["name"]), None)
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, effective_from=body.effective_from,
                            allocable_cost_yen=((selected.fixed_cost_yen + selected.variable_cost_yen) if selected and selected.fixed_cost_yen is not None and selected.variable_cost_yen is not None else None),
                            period_total_person_hours=selected.H_period_bill if selected else None, u_period=1 if selected else None,
                            costs=excluded, evidence=evidence, source=body.source, notes=f"選択シナリオ: {body.selected_scenario or '未選択'}")
    calc = RateCalculation(status=RateStatus.blocked if blockers else RateStatus.draft,
                           candidate_yen_per_person_hour=chosen["rate_yen_per_person_hour"] if not blockers else None,
                           denominator_person_hours=selected.H_period_bill if selected else None, u_period=1 if selected else None,
                           unknowns=blockers, excluded_items=excluded, basis=basis)
    return store.create_proposal(proposal, module_calculation=calc)
