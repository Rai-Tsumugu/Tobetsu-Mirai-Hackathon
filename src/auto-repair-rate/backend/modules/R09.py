"""R09 winter cost comparison API with an explicit price-policy gate."""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field
from typing import Literal

from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r09_winter_allocation import calculate_winter_scenario

MODULE_ID = "R09"
router = APIRouter(tags=["R09 winter cost allocation"])


class R09Create(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    annual_period_start: date
    annual_period_end: date
    source_date: date
    winter_start_month: int = Field(ge=1, le=12)
    winter_end_month: int = Field(ge=1, le=12)
    effective_from: date
    winter_cost_yen: float | None = Field(default=None, ge=0)
    winter_billable_hours: float | None = Field(default=None, ge=0)
    annual_baseline_rate: float | None = Field(default=None, ge=0)
    annual_billable_hours: float | None = Field(default=None, ge=0)
    selected_scenario: Literal["annual_baseline", "winter_scenario"] | None = None
    price_policy_confirmed: bool = False
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


def _result(body: R09Create):
    result = calculate_winter_scenario(winter_cost_yen=body.winter_cost_yen,
                                     winter_billable_hours=body.winter_billable_hours,
                                     annual_baseline_rate=body.annual_baseline_rate,
                                     annual_billable_hours=body.annual_billable_hours,
                                     price_policy_confirmed=True)
    result["price_policy_confirmed"] = body.price_policy_confirmed
    if not _is_one_year_inclusive(body.annual_period_start, body.annual_period_end):
        result["common_blockers"].append("年間対象期間は開始日から1年間の期間を指定してください")
        result["baseline_available"] = False
        result["winter_available"] = False
        result["available"] = False
        result["blockers"].append("年間対象期間は開始日から1年間の期間を指定してください")
    return result


@router.post("/rates/preview")
def preview(body: R09Create):
    return _result(body)


@router.post("/proposals")
def create_proposal(body: R09Create):
    result = _result(body)
    period_blockers = []
    blockers = list(result["common_blockers"])
    if body.selected_scenario is None:
        blockers.append("共有候補にする単価案を選択してください")
    elif body.selected_scenario == "winter_scenario":
        blockers.extend(result["winter_blockers"])
        if not body.price_policy_confirmed:
            blockers.append("冬季候補の共有承認前に価格方針を確認してください")
    blockers.extend(period_blockers)
    now = datetime.now(timezone.utc)
    basis = [BasisRow(label="年間基準単価", value=body.annual_baseline_rate, unit="円/人時"),
             BasisRow(label="冬季費用", value=body.winter_cost_yen, unit="円/冬季"),
             BasisRow(label="冬季請求可能人時", value=body.winter_billable_hours, unit="人時/冬季"),
             BasisRow(label="冬季候補単価", value=result["winter_candidate_rate"], unit="円/人時"),
             BasisRow(label="通年基準との差", value=result["delta_yen_per_person_hour"], unit="円/人時"),
             BasisRow(label="冬季に適用した場合の年影響", value=result["annual_impact_yen"], unit="円/年"),
             BasisRow(label="既定適用", value=False, unit="boolean"),
             BasisRow(label="価格方針確認", value=body.price_policy_confirmed, unit="boolean"),
             BasisRow(label="対象期間・冬季", value=f"{body.annual_period_start}〜{body.annual_period_end}; {body.winter_start_month}〜{body.winter_end_month}月", unit="期間"),
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
    evidence = [Evidence(label="冬季費用・請求可能人時・年間基準の根拠", value=body.evidence_notes, unit="説明",
                         status="assumed" if body.source == "架空シミュレータ" else "entered",
                         source=body.source, evidence_ref=body.evidence_ref, recorded_at=now,
                         notes="冬季案は既定で未適用。価格方針確認後も人が共通承認します")]
    blockers = sorted(set(blockers))
    # The shared approval endpoint can create the common labor_rate only for a complete, policy-confirmed proposal.
    candidate = (body.annual_baseline_rate if body.selected_scenario == "annual_baseline" else result["winter_candidate_rate"])
    if blockers:
        candidate = None
    denominator_hours = (body.annual_billable_hours if body.selected_scenario == "annual_baseline"
                        else body.winter_billable_hours)
    derived_allocable_cost = candidate * denominator_hours if candidate is not None and denominator_hours is not None else None
    basis.extend([
        BasisRow(label="共有候補の選択案", value=body.selected_scenario, unit="scenario"),
        BasisRow(label="共有候補の配賦費用合計（単価×分母から導出）", value=derived_allocable_cost, unit="円/対象期間"),
    ])
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.annual_period_start, period_end=body.annual_period_end,
                            effective_from=body.effective_from, allocable_cost_yen=derived_allocable_cost,
                            period_total_person_hours=denominator_hours, u_period=1 if denominator_hours else None,
                            costs=excluded, evidence=evidence, source=body.source,
                            notes=(f"R09 selected_scenario={body.selected_scenario}; candidate aggregate cost is derived as "
                                   "approved candidate rate * matching selected-period billable hours; "
                                   "winter scenario remains unapplied unless selected and human-approved."))
    calculation = RateCalculation(status=RateStatus.blocked if blockers else RateStatus.draft,
                                  candidate_yen_per_person_hour=candidate,
                                  denominator_person_hours=denominator_hours,
                                  u_period=1 if denominator_hours else None,
                                  unknowns=blockers, excluded_items=excluded, basis=basis)
    rate_scope = ("factory_standard" if body.selected_scenario == "annual_baseline"
                  else "season:winter" if body.selected_scenario == "winter_scenario"
                  else "factory_standard")
    return store.create_proposal(proposal, module_calculation=calculation,
                                 rate_scope=rate_scope, rate_type="customer")


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "R09 proposal not found")
    return store.get_proposal(proposal_id)
