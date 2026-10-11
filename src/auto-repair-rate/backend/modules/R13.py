"""R13 step cards for annualizing cost inputs, delegated to R01 on server."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import ConfigDict, Field

from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r13_cost_wizard import calculate_wizard

MODULE_ID = "R13"
router = APIRouter(tags=["R13 quick cost wizard"])


class CostCard(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["rent", "heating", "equipment", "payroll", "materials"]
    label: str = Field(min_length=1)
    amount: float | None = Field(default=None, ge=0)
    period: Literal["monthly", "annual"]
    include_flag: bool
    status: Literal["confirmed", "provided", "estimated", "unknown"] = "unknown"
    source: str | None = None
    notes: str | None = None


class R13Create(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    cards: list[CostCard] = Field(min_length=4)
    total_person_hours: float | None = Field(default=None, ge=0)
    u_period: float | None = Field(default=None, ge=0, le=1)
    period_start: str = Field(min_length=10)
    period_end: str = Field(min_length=10)
    effective_from: str = Field(min_length=10)
    source_date: str = Field(min_length=10)
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    confirm_payroll_overlap: bool = False


def _result(body: R13Create):
    return calculate_wizard([card.model_dump() for card in body.cards], body.total_person_hours,
                            body.u_period, body.period_start, body.period_end, body.effective_from,
                            body.confirm_payroll_overlap)


@router.post("/rates/preview")
def preview(body: R13Create):
    return _result(body)


@router.post("/proposals")
def create_proposal(body: R13Create):
    result = _result(body)
    now = datetime.now(timezone.utc)
    cards = [card.model_dump() for card in body.cards]
    # R01 is the single source of truth for money and billable-hour validation.
    included = [row for row in result["included_costs"] if row["included_in_rate"]]
    included_total = sum(row["amount_yen"] or 0 for row in included) if not result["blockers"] else None
    from backend.models import CostItem
    excluded = [CostItem(cost_id=row["id"], label=row["label"], amount_yen=row["amount_yen"], period=f"{body.period_start}〜{body.period_end}",
                         source=row["source"], evidence_status="unknown" if row["status"] == "unknown" else ("assumed" if row["status"] == "estimated" else "entered"),
                         billing_class="separately_billed_item", included_in_labor_pool=False)
                for row in result["excluded_costs"]]
    evidence = [Evidence(label="費目カード入力", value=body.evidence_notes, unit="説明", status="assumed" if "架空" in body.source else "entered",
                         source=body.source, evidence_ref=body.evidence_ref, recorded_at=now,
                         notes="月額は12倍、年額はそのまま。空欄は不明のまま停止")]
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, period_end=body.period_end,
                            effective_from=body.effective_from, allocable_cost_yen=included_total,
                            period_total_person_hours=body.total_person_hours, u_period=body.u_period,
                            costs=excluded, evidence=evidence, source=body.source, notes="R13 normalized inputs through R01 server calculation")
    shared = result["shared_calculation"]
    calc = RateCalculation(status=RateStatus.blocked if result["blockers"] else RateStatus.draft,
                           candidate_yen_per_person_hour=float(result["candidate_yen_per_person_hour"]) if not result["blockers"] else None,
                           denominator_person_hours=shared["denominator_person_hours"], u_period=body.u_period,
                           unknowns=sorted(set(result["blockers"])), excluded_items=excluded,
                           basis=[BasisRow(label="月額・年額の明示換算", value=f"{len(cards)}費目", unit=result["normalization"]),
                                  BasisRow(label="根拠資料日", value=body.source_date, unit="日付"),
                                  BasisRow(label="根拠参照", value=body.evidence_ref, unit="source_ref"),
                                  BasisRow(label="給与重複の人手確認", value=body.confirm_payroll_overlap, unit="確認"),
                                  *[BasisRow(label=item["label"], value=item["amount_yen"], unit="円/年") for item in result["included_costs"]]])
    if calc.candidate_yen_per_person_hour is None:
        calc.status = RateStatus.blocked
        calc.unknowns = sorted(set(calc.unknowns + shared["unknowns"]))
    return store.create_proposal(proposal, module_calculation=calc)
