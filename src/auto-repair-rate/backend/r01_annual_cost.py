"""R01 annual cost stack-up calculation.

Pure, persistence-free simulator slice. Results are candidates and never issue an
approved labor_rate. Amounts and sources in the paired fixture are fictional.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from backend.models import CostItem as SharedCostItem
from backend.models import EvidenceStatus, HoursRange, RateProposal
from backend.shared import calculate as calculate_shared


CostStatus = Literal["confirmed", "provided", "estimated", "unknown"]
HOURS_BASES = {"total_person_hours", "billable_person_hours"}
EXCLUDED_CATEGORIES = {"parts", "materials"}


@dataclass(frozen=True)
class CostRow:
    id: str
    category: str
    label: str
    amount_yen: int | float | None
    included_in_rate: bool
    status: CostStatus
    source: str | None
    evidence: str | None
    payroll_overlap: bool = False
    payroll_overlap_confirmed: bool = True


@dataclass(frozen=True)
class AnnualCostInput:
    period_label: str
    costs: tuple[CostRow, ...]
    H_period_total: Decimal | None
    u_period: Decimal | None
    annual_allocable_cost_yen: int | float | None = None
    period_start: str = "2025-01-01"
    period_end: str | None = "2025-12-31"
    effective_from: str = "2026-01-01"
    hours_basis: str | None = None
    job_billable_ratio: Decimal | None = None
    job_person_hours: dict[str, float] | None = None


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} must be a finite number") from None
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite number")
    return result


def _whole_yen(value: Any) -> bool:
    try:
        amount = _decimal(value, "amount_yen")
    except ValueError:
        return False
    return amount >= 0 and amount == amount.to_integral_value()


def job_billable_hours(hours: Any, hours_basis: str,
                       job_billable_ratio: Any = None) -> Decimal:
    """Apply the job ratio only to total-person-hour inputs.

    This helper is separate from R01's period utilization u_period.
    """
    person_hours = _decimal(hours, "hours")
    if person_hours < 0:
        raise ValueError("hours must be non-negative")
    if hours_basis == "billable_person_hours":
        return person_hours
    if hours_basis != "total_person_hours":
        raise ValueError("hours_basis is not recognized")
    if job_billable_ratio is None:
        raise ValueError("job_billable_ratio is required for total_person_hours")
    ratio = _decimal(job_billable_ratio, "job_billable_ratio")
    if ratio < 0 or ratio > 1:
        raise ValueError("job_billable_ratio must be between 0 and 1")
    return person_hours * ratio


def calculate_annual_cost(data: AnnualCostInput | dict[str, Any]) -> dict[str, Any]:
    """Return a candidate preview or blockers, preserving excluded cost evidence."""
    if isinstance(data, dict):
        rows = tuple(CostRow(**row) for row in data.get("costs", ()))
        data = AnnualCostInput(
            period_label=data.get("period_label", ""),
            costs=rows,
            H_period_total=data.get("H_period_total"),
            u_period=data.get("u_period"),
            annual_allocable_cost_yen=data.get("annual_allocable_cost_yen"),
            period_start=data.get("period_start", "2025-01-01"),
            period_end=data.get("period_end", "2025-12-31"),
            effective_from=data.get("effective_from", "2026-01-01"),
            hours_basis=data.get("hours_basis"),
            job_billable_ratio=data.get("job_billable_ratio"),
            job_person_hours=data.get("job_person_hours"),
        )

    blockers: list[str] = []
    included_sum = 0
    included_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in data.costs:
        if not row.id or row.id in seen_ids:
            blockers.append(f"費目IDが空または重複しています: {row.id or '(空欄)'}")
        seen_ids.add(row.id)
        row_data = asdict(row)
        if row.amount_yen is not None and not _whole_yen(row.amount_yen):
            blockers.append(f"{row.label}: 金額は整数の円で入力してください")
        if row.included_in_rate and row.category in EXCLUDED_CATEGORIES:
            blockers.append(f"{row.label}: 部品・材料費は工賃原価から除外してください")
        if row.included_in_rate:
            included_rows.append(row_data)
            if row.status == "unknown" or row.amount_yen is None:
                blockers.append(f"{row.label}: 計上額が不明です")
            elif _whole_yen(row.amount_yen):
                included_sum += int(row.amount_yen)
            if not row.source or not row.evidence:
                blockers.append(f"{row.label}: 計上根拠と出典が必要です")
            if row.payroll_overlap:
                blockers.append(f"{row.label}: 人件費との重複計上の確認が必要です")
            if not row.payroll_overlap_confirmed:
                blockers.append(f"{row.label}: 人件費との重複がないことを確認してください")
        else:
            excluded_rows.append(row_data)

    try:
        if data.H_period_total is None:
            raise ValueError("年間総労働人時が不明です")
        total_hours = _decimal(data.H_period_total, "H_period_total")
        if total_hours <= 0:
            raise ValueError("年間総労働人時は0より大きい値が必要です")
    except ValueError as exc:
        blockers.append(str(exc))
        total_hours = None
    try:
        if data.u_period is None:
            raise ValueError("期間の請求可能割合 u_period が不明です")
        utilization = _decimal(data.u_period, "u_period")
        if utilization <= 0 or utilization > 1:
            raise ValueError("u_period は0より大きく1以下にしてください")
    except ValueError as exc:
        blockers.append(str(exc))
        utilization = None

    billable_hours = total_hours * utilization if total_hours is not None and utilization is not None else None
    if billable_hours == 0:
        blockers.append("請求可能人時が0のため試算できません")
    if data.annual_allocable_cost_yen is not None:
        if not _whole_yen(data.annual_allocable_cost_yen):
            blockers.append("年間配賦費用は整数の円で入力してください")
        elif data.costs and data.annual_allocable_cost_yen != included_sum:
            blockers.append("配賦費用合計と計上費目の合計が一致しません")
    if data.annual_allocable_cost_yen is not None:
        included_sum = int(data.annual_allocable_cost_yen) if _whole_yen(data.annual_allocable_cost_yen) else data.annual_allocable_cost_yen

    shared_costs = []
    for row in data.costs:
        status_map = {
            "confirmed": EvidenceStatus.factory_reported,
            "provided": EvidenceStatus.entered,
            "estimated": EvidenceStatus.assumed,
            "unknown": EvidenceStatus.unknown,
        }
        shared_costs.append(SharedCostItem(
            cost_id=row.id,
            label=row.label,
            amount_yen=row.amount_yen,
            period=data.period_label,
            source=row.source,
            evidence_status=status_map[row.status],
            billing_class=("separately_billed_item" if row.category in EXCLUDED_CATEGORIES else "labor_pool"),
            included_in_labor_pool=(row.included_in_rate and row.category not in EXCLUDED_CATEGORIES),
            excluded_reason="工賃と別請求する部品・材料費" if row.category in EXCLUDED_CATEGORIES else None,
        ))
    shared_proposal = RateProposal(
        module_id="R01",
        period_start=data.period_start,
        period_end=data.period_end,
        effective_from=data.effective_from,
        allocable_cost_yen=(float(included_sum) if not blockers else data.annual_allocable_cost_yen),
        period_total_person_hours=float(total_hours) if total_hours is not None else None,
        u_period=float(utilization) if utilization is not None else None,
        hours_basis=data.hours_basis,
        job_person_hours=HoursRange(**data.job_person_hours) if data.job_person_hours else None,
        job_billable_ratio=(float(data.job_billable_ratio) if data.job_billable_ratio is not None else None),
        costs=shared_costs,
        source="fictional_simulator",
        notes="R01 annual-cost calculation; fictional/demo inputs only.",
    )
    common = calculate_shared(shared_proposal)
    candidate = Decimal(str(common.candidate_yen_per_person_hour)) if common.candidate_yen_per_person_hour is not None and not blockers else None
    return {
        "period_label": data.period_label,
        "annual_allocable_cost_yen": included_sum if not blockers else None,
        "included_costs": included_rows,
        "excluded_costs": excluded_rows,
        "H_period_total": str(total_hours) if total_hours is not None else None,
        "u_period": str(utilization) if utilization is not None else None,
        "H_period_bill": str(billable_hours) if billable_hours is not None else None,
        "formula": "annual_allocable_cost / (H_period_total * u_period)",
        "candidate_yen_per_person_hour": format(candidate.normalize(), "f") if candidate is not None else None,
        "candidate_status": "candidate" if candidate is not None else "blocked",
        "approval_status": "pending_human_approval",
        "labor_rate_issued": False,
        "blockers": blockers + common.unknowns,
        "shared_calculation": common.model_dump(mode="json"),
        "hours_basis": data.hours_basis,
        "job_billable_ratio": str(data.job_billable_ratio) if data.job_billable_ratio is not None else None,
        "job_ratio_applied_to_period_denominator": False,
    }
