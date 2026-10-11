"""R10 twelve-month rolling smoothing API."""
from calendar import monthrange
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field

from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r10_rolling_smoothing import calculate_rolling_smoothing

MODULE_ID = "R10"
router = APIRouter(tags=["R10 rolling cost smoothing"])


class R10Create(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    period_end: date
    source_date: date
    invoice_month: int = Field(ge=1, le=12)
    effective_from: date
    monthly_cost_yen: list[float | None] = Field(default_factory=list)
    monthly_total_person_hours: list[float | None] = Field(default_factory=list)
    monthly_u_period: list[float | None] = Field(default_factory=list)
    seasonal_allocation_already_applied: bool = False
    materials_yen: float | None = Field(default=None, ge=0)
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)


def _result(body: R10Create):
    return calculate_rolling_smoothing(monthly_cost_yen=body.monthly_cost_yen,
                                      monthly_total_person_hours=body.monthly_total_person_hours,
                                      monthly_u_period=body.monthly_u_period, invoice_month=body.invoice_month,
                                      seasonal_allocation_already_applied=body.seasonal_allocation_already_applied)


@router.post("/rates/preview")
def preview(body: R10Create):
    return _result(body)


@router.post("/proposals")
def create_proposal(body: R10Create):
    result = _result(body)
    month_span = (body.period_end.year - body.period_start.year) * 12 + body.period_end.month - body.period_start.month
    expected_last_day = monthrange(body.period_end.year, body.period_end.month)[1]
    if month_span != 11 or body.period_start.day != 1 or body.period_end.day != expected_last_day:
        result["blockers"].append("対象期間は月初から月末までの連続12か月で指定してください")
    now = datetime.now(timezone.utc)
    basis = [BasisRow(label="対象期間", value=f"{body.period_start}〜{body.period_end}", unit="12か月"),
             BasisRow(label="比較する請求月", value=body.invoice_month, unit="月"),
             BasisRow(label="請求月の生単価", value=result["raw_invoice_month_rate"], unit="円/人時"),
             BasisRow(label="12か月費用合計", value=result["total_allocable_cost_yen"], unit="円"),
             BasisRow(label="12か月請求可能人時合計", value=result["total_billable_hours"], unit="人時"),
             BasisRow(label="平準化単価", value=result["smoothed_rate"], unit="円/人時"),
             BasisRow(label="平準化式", value=result["formula"], unit="式"),
             BasisRow(label="季節配賦の二重計上確認", value=body.seasonal_allocation_already_applied, unit="boolean"),
             BasisRow(label="根拠記録日", value=now.date().isoformat(), unit="日付"),
             BasisRow(label="原資料の日付", value=body.source_date.isoformat(), unit="日付"),
             BasisRow(label="根拠参照", value=body.evidence_ref, unit="source_ref")]
    excluded = []
    if body.materials_yen is not None:
        from backend.models import CostItem
        excluded = [CostItem(cost_id="separately_billed_materials", label="別請求の部品・材料費", amount_yen=body.materials_yen,
                             period=f"{body.period_start}〜{body.period_end}", source=body.source,
                             evidence_status="assumed" if body.source == "架空シミュレータ" else "entered",
                             billing_class="separately_billed_item", included_in_labor_pool=False)]
        basis.append(BasisRow(label="別請求材料（除外）", value=body.materials_yen, unit="円"))
    evidence = [Evidence(label="12か月費用・人時・稼働率の根拠", value=body.evidence_notes, unit="説明",
                         status="assumed" if body.source == "架空シミュレータ" else "entered",
                         source=body.source, evidence_ref=body.evidence_ref, recorded_at=now,
                         notes="12か月分がすべて既知の場合にだけ平準化候補を算出")]
    blockers = sorted(set(result["blockers"]))
    cost = result["total_allocable_cost_yen"]
    hours = result["total_billable_hours"]
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, period_end=body.period_end,
                            effective_from=body.effective_from, allocable_cost_yen=cost,
                            period_total_person_hours=hours, u_period=1 if hours else None,
                            costs=excluded, evidence=evidence, source=body.source,
                            notes="R10 total allocable cost / total billable hours; seasonal allocation double count is blocked.")
    calculation = RateCalculation(status=RateStatus.blocked if blockers else RateStatus.draft,
                                  candidate_yen_per_person_hour=result["smoothed_rate"] if not blockers else None,
                                  denominator_person_hours=hours, u_period=1 if hours else None,
                                  unknowns=blockers, excluded_items=excluded, basis=basis)
    return store.create_proposal(proposal, module_calculation=calculation)


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "R10 proposal not found")
    return store.get_proposal(proposal_id)
