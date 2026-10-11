"""R14 reviewed local CSV import. Original CSV text is never persisted."""
from datetime import date, datetime, timezone

from fastapi import APIRouter
from pydantic import ConfigDict, Field
from typing import Literal

from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r14_csv_import import parse_cost_csv

MODULE_ID = "R14"
router = APIRouter(tags=["R14 CSV cost import"])


class AccountMapping(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    account: str = Field(min_length=1)
    category: Literal["rent", "heating", "equipment", "payroll", "materials"]
    approved: bool = False


class R14Create(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    csv_contents: str = Field(min_length=1)
    mappings: list[AccountMapping]
    confirm_materials_exclusion: bool = False
    confirm_duplicate_exclusion: bool = False
    tax_basis: Literal["tax_excluded"] = "tax_excluded"
    period_start: date
    period_end: date
    effective_from: date
    source: str = Field(min_length=1)
    source_date: date
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    H_period_total: float | None = Field(default=None, ge=0)
    u_period: float | None = Field(default=None, ge=0, le=1)


def _result(body: R14Create):
    return parse_cost_csv(body.csv_contents, [m.model_dump() for m in body.mappings],
                          body.confirm_materials_exclusion, body.confirm_duplicate_exclusion,
                          body.period_start, body.period_end, body.tax_basis)


@router.post("/rates/preview")
def preview(body: R14Create):
    return _result(body)


@router.post("/proposals")
def create_proposal(body: R14Create):
    result = _result(body)
    now = datetime.now(timezone.utc)
    costs_total = sum(sum(values for category, values in result["allocated_totals_yen"].items()) for _ in [0]) if not result["blockers"] else None
    blockers = result["blockers"][:]
    rows = result["rows"]
    if body.H_period_total is None or body.u_period is None:
        blockers.append("期間の人時または請求可能割合 u_period が不明です")
    elif body.H_period_total * body.u_period <= 0:
        blockers.append("請求可能人時が0のため試算できません")
    from backend.models import CostItem
    materials_total = sum(row["amount_yen"] for row in rows if row["mapped_category"] == "materials" and row["mapping_approved"])
    excluded = [CostItem(cost_id="csv_materials_excluded", label="CSVの別請求部品・材料", amount_yen=materials_total,
                         period=f"{body.period_start}〜{body.period_end}", source=body.source,
                         evidence_status="assumed" if "架空" in body.source else "entered",
                         billing_class="separately_billed_item", included_in_labor_pool=False)] if materials_total else []
    evidence = [Evidence(label="ローカルCSV行プレビュー", value=f"{len(rows)}行。元CSVは保存せず、承認済み対応科目の集計だけを保存", unit="説明",
                         status="assumed" if "架空" in body.source else "entered", source=body.source,
                         evidence_ref=body.evidence_ref, recorded_at=now,
                         notes=f"{body.evidence_notes}; 重複除外確認={body.confirm_duplicate_exclusion}; 材料除外確認={body.confirm_materials_exclusion}")]
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, period_end=body.period_end,
                            effective_from=body.effective_from, allocable_cost_yen=costs_total,
                            period_total_person_hours=body.H_period_total, u_period=body.u_period,
                            costs=excluded, evidence=evidence, source=body.source, notes="CSV rows transiently parsed; source text not retained")
    denominator = body.H_period_total * body.u_period if body.H_period_total is not None and body.u_period is not None else None
    candidate = costs_total / denominator if costs_total is not None and denominator and not blockers else None
    basis = [BasisRow(label="CSV行数", value=len(rows), unit="行"),
             BasisRow(label="承認済み配賦費用", value=costs_total, unit="円/期間"),
             BasisRow(label="請求可能人時分母", value=denominator, unit="人時/期間"),
             BasisRow(label="原資料日・参照", value=f"{body.source_date} / {body.evidence_ref}", unit="source_ref"),
             BasisRow(label="CSV保管", value=False, unit="元テキストは保存しない")]
    calc = RateCalculation(status=RateStatus.blocked if candidate is None else RateStatus.draft,
                           candidate_yen_per_person_hour=candidate, denominator_person_hours=denominator,
                           u_period=body.u_period, unknowns=sorted(set(blockers)), excluded_items=excluded, basis=basis)
    return store.create_proposal(proposal, module_calculation=calc)
