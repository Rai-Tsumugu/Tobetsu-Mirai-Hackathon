"""R08 annual heating allocation API."""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field

from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r08_annual_heating import calculate_annual_heating_rate

MODULE_ID = "R08"
router = APIRouter(tags=["R08 annual heating allocation"])


class R08Create(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    annual_period_start: date
    annual_period_end: date
    source_date: date
    effective_from: date
    annual_heating_cost_yen: float | None = Field(default=None, ge=0)
    other_allocable_cost_yen: float | None = Field(default=None, ge=0)
    annual_billable_hours: float | None = Field(default=None, ge=0)
    materials_yen: float | None = Field(default=None, ge=0)
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)


def _is_one_year_inclusive(start: date, end: date) -> bool:
    try:
        anniversary = start.replace(year=start.year + 1)
    except ValueError:  # February 29: the next anniversary is March 1.
        anniversary = date(start.year + 1, 3, 1)
    return end == anniversary - timedelta(days=1)


def _result(body: R08Create):
    result = calculate_annual_heating_rate(annual_heating_cost_yen=body.annual_heating_cost_yen,
                                          other_allocable_cost_yen=body.other_allocable_cost_yen,
                                          annual_billable_hours=body.annual_billable_hours)
    if not _is_one_year_inclusive(body.annual_period_start, body.annual_period_end):
        result["blockers"].append("年間対象期間は開始日から1年間の期間を指定してください")
        result["available"] = False
    return result


@router.post("/rates/preview")
def preview(body: R08Create):
    return _result(body)


@router.post("/proposals")
def create_proposal(body: R08Create):
    result = _result(body)
    now = datetime.now(timezone.utc)
    cost = result["annual_allocable_cost_yen"]
    hours = body.annual_billable_hours
    basis = [BasisRow(label="年間配賦期間", value=f"{body.annual_period_start}〜{body.annual_period_end}", unit="期間"),
             BasisRow(label="年間暖房費", value=body.annual_heating_cost_yen, unit="円/年"),
             BasisRow(label="その他年間配賦費用", value=body.other_allocable_cost_yen, unit="円/年"),
             BasisRow(label="年間請求可能人時", value=hours, unit="人時/年"),
             BasisRow(label="暖房費配賦率", value=result["annual_heating_rate"], unit="円/人時"),
             BasisRow(label="その他費用配賦率", value=result["annual_base_rate"], unit="円/人時"),
             BasisRow(label="配賦期間", value="年間。冬季だけの加算なし", unit="説明"),
             BasisRow(label="根拠記録日", value=now.date().isoformat(), unit="日付"),
             BasisRow(label="原資料の日付", value=body.source_date.isoformat(), unit="日付"),
             BasisRow(label="根拠参照", value=body.evidence_ref, unit="source_ref")]
    excluded = []
    if body.materials_yen is not None:
        from backend.models import CostItem
        excluded = [CostItem(cost_id="separately_billed_materials", label="別請求の部品・材料費", amount_yen=body.materials_yen,
                             period=f"{body.annual_period_start}〜{body.annual_period_end}", source=body.source,
                             evidence_status="assumed" if body.source == "架空シミュレータ" else "entered",
                             billing_class="separately_billed_item", included_in_labor_pool=False)]
        basis.append(BasisRow(label="別請求材料（除外）", value=body.materials_yen, unit="円"))
    evidence = [Evidence(label="年間費用・請求可能人時の根拠", value=body.evidence_notes, unit="説明",
                         status="assumed" if body.source == "架空シミュレータ" else "entered",
                         source=body.source, evidence_ref=body.evidence_ref, recorded_at=now,
                         notes="暖房費を含む費用を年間請求可能人時へ配賦")]
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.annual_period_start, period_end=body.annual_period_end,
                            effective_from=body.effective_from, allocable_cost_yen=cost,
                            period_total_person_hours=hours, u_period=1 if hours and hours > 0 else None,
                            costs=excluded, evidence=evidence, source=body.source,
                            notes="年間暖房費 / 年間請求可能人時 + その他年間費用 / 同一分母")
    status = RateStatus.blocked if result["blockers"] else RateStatus.draft
    calculation = RateCalculation(status=status, candidate_yen_per_person_hour=result["candidate_yen_per_person_hour"] if status == RateStatus.draft else None,
                                  denominator_person_hours=hours, u_period=1 if hours and hours > 0 else None,
                                  unknowns=result["blockers"], excluded_items=excluded, basis=basis)
    return store.create_proposal(proposal, module_calculation=calculation)


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "R08 proposal not found")
    return store.get_proposal(proposal_id)
