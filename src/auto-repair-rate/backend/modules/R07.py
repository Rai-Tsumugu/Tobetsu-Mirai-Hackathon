"""R07 category cost-pool allocation API."""
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field

from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r07_department_cost_pools import CATEGORIES, calculate_department_rates

MODULE_ID = "R07"
router = APIRouter(tags=["R07 department cost pools"])


class R07Create(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    source_date: date
    effective_from: date
    direct_cost_yen: dict[str, float | None] = Field(default_factory=dict)
    shared_cost_yen: float | None = None
    allocation_key: dict[str, float | None] = Field(default_factory=dict)
    total_person_hours: dict[str, float | None] = Field(default_factory=dict)
    u_period: dict[str, float | None] = Field(default_factory=dict)
    selected_category: str | None = None
    allocation_confirmed: bool = False
    materials_yen: float | None = Field(default=None, ge=0)
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)


def _calculate(body: R07Create) -> dict[str, Any]:
    result = calculate_department_rates(direct_cost_yen=body.direct_cost_yen, shared_cost_yen=body.shared_cost_yen,
                                       allocation_key=body.allocation_key, total_person_hours=body.total_person_hours,
                                       u_period=body.u_period)
    if set(body.direct_cost_yen) != set(CATEGORIES) or set(body.allocation_key) != set(CATEGORIES) or set(body.total_person_hours) != set(CATEGORIES) or set(body.u_period) != set(CATEGORIES):
        result["blockers"].append("カテゴリは整備・鈑金塗装の2区分を正確に入力してください")
    if not body.allocation_confirmed:
        result["blockers"].append("共通費の配賦先と配賦キーを確認してください")
    if body.selected_category not in CATEGORIES:
        result["blockers"].append("共有候補にするカテゴリを明示してください")
    result["available"] = not result["blockers"]
    return result


@router.post("/rates/preview")
def preview(body: R07Create):
    result = _calculate(body)
    return result


@router.post("/proposals")
def create_proposal(body: R07Create):
    result = _calculate(body)
    now = datetime.now(timezone.utc)
    category = body.selected_category
    candidate = result["rate_yen_per_person_hour"].get(category) if category in CATEGORIES else None
    basis = [BasisRow(label="対象カテゴリ", value=category, unit="category"),
             BasisRow(label="共通費元金額", value=body.shared_cost_yen, unit="円"),
             BasisRow(label="カテゴリ別配賦後費用", value=result["category_cost_yen"].get(category), unit="円/期間"),
             BasisRow(label="カテゴリ別請求可能人時", value=result["denominator_billable_hours"].get(category), unit="人時/期間"),
             BasisRow(label="共通費配賦合計", value=result["reconciled_shared_cost_yen"], unit="円"),
             BasisRow(label="元費用との一致", value=result["reconciles"], unit="boolean"),
             BasisRow(label="配賦キー・整備", value=body.allocation_key.get(CATEGORIES[0]), unit="配賦キー"),
             BasisRow(label="配賦キー・鈑金塗装", value=body.allocation_key.get(CATEGORIES[1]), unit="配賦キー"),
             BasisRow(label="根拠記録日", value=now.date().isoformat(), unit="日付"),
             BasisRow(label="原資料の日付", value=body.source_date.isoformat(), unit="日付"),
             BasisRow(label="根拠参照", value=body.evidence_ref, unit="source_ref")]
    if body.materials_yen is not None:
        basis.append(BasisRow(label="別請求塗料・材料（除外）", value=body.materials_yen, unit="円"))
    evidence = [Evidence(label="R07費用・配賦・人時根拠", value=body.evidence_notes, unit="説明",
                         status="assumed" if body.source == "架空シミュレータ" else "entered",
                         source=body.source, evidence_ref=body.evidence_ref,
                         recorded_at=now, notes="別請求の塗料・材料は労務原価に含めません")]
    excluded = []
    if body.materials_yen is not None:
        from backend.models import CostItem
        excluded = [CostItem(cost_id="separately_billed_materials", label="別請求の塗料・材料費", amount_yen=body.materials_yen,
                             period=body.period_start.isoformat(), source=body.source,
                             evidence_status="assumed" if body.source == "架空シミュレータ" else "entered",
                             billing_class="separately_billed_item", included_in_labor_pool=False)]
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, effective_from=body.effective_from,
                            allocable_cost_yen=result["category_cost_yen"].get(category) if category in CATEGORIES else None,
                            period_total_person_hours=body.total_person_hours.get(category) if category in CATEGORIES else None,
                            u_period=body.u_period.get(category) if category in CATEGORIES else None,
                            costs=excluded, evidence=evidence, source=body.source,
                            notes="R07 category rate uses C[c] / (H_total[c] * u_period[c]); separately billed materials excluded.")
    calculation = RateCalculation(status=RateStatus.blocked if result["blockers"] else RateStatus.draft,
                                  candidate_yen_per_person_hour=candidate if not result["blockers"] else None,
                                  denominator_person_hours=result["denominator_billable_hours"].get(category) if category in CATEGORIES else None,
                                  u_period=body.u_period.get(category) if category in CATEGORIES else None,
                                  unknowns=result["blockers"], excluded_items=excluded, basis=basis)
    rate_scope = f"category:{category}" if category in CATEGORIES else "factory_standard"
    return store.create_proposal(proposal, module_calculation=calculation,
                                 rate_scope=rate_scope, rate_type="customer")


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "R07 proposal not found")
    return store.get_proposal(proposal_id)
