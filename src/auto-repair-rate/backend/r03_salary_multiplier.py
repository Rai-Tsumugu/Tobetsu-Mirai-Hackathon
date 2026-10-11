"""R03 salary-multiplier comparison candidate, never a formal cost formula."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .models import BasisRow, RateCalculation, RateProposal, RateStatus
from .shared import calculate as calculate_shared


def _decimal(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def calculate_salary_multiplier(
    proposal: RateProposal,
    daily_pay_yen: Any,
    paid_days_per_year: Any,
    approved_multiplier: Any,
    multiplier_approved_by: str | None,
    salary_basis_acknowledged: bool,
) -> RateCalculation:
    """Calculate annual daily pay * multiplier / period billable hours.

    All values are supplied by the API caller; the server derives the result.
    Missing/zero required inputs and missing human confirmations are saved as
    blocked results. The three-times value is only a fictional starting example.
    """
    blockers: list[str] = []
    pay = _decimal(daily_pay_yen, "daily_pay_yen")
    days = _decimal(paid_days_per_year, "paid_days_per_year")
    multiplier = _decimal(approved_multiplier, "approved_multiplier")
    total_hours = _decimal(proposal.period_total_person_hours, "period_total_person_hours")
    u_period = _decimal(proposal.u_period, "u_period")

    for field, value in (("daily_pay_yen", pay), ("paid_days_per_year", days),
                         ("approved_multiplier", multiplier),
                         ("period_total_person_hours", total_hours), ("u_period", u_period)):
        if value is None:
            blockers.append(f"{field}_unknown_or_not_finite")
    if pay is not None and pay <= 0:
        blockers.append("daily_pay_yen_must_be_greater_than_zero")
    if days is not None and days <= 0:
        blockers.append("paid_days_per_year_must_be_greater_than_zero")
    if multiplier is not None and multiplier <= 0:
        blockers.append("approved_multiplier_must_be_greater_than_zero")
    if total_hours is not None and total_hours < 0:
        blockers.append("period_total_person_hours_must_not_be_negative")
    if u_period is not None and not Decimal(0) <= u_period <= Decimal(1):
        blockers.append("u_period_must_be_between_zero_and_one")
    if not multiplier_approved_by or not multiplier_approved_by.strip():
        blockers.append("multiplier_approval_by_president_required")
    if not salary_basis_acknowledged:
        blockers.append("salary_multiplier_comparison_acknowledgement_required")

    denominator: Decimal | None = None
    if total_hours is not None and u_period is not None and total_hours >= 0 and Decimal(0) <= u_period <= Decimal(1):
        denominator = total_hours * u_period
        if denominator <= 0:
            blockers.append("required_denominator_is_zero")

    # Reuse shared job-hours semantics (total hours receive job_billable_ratio
    # once; already-billable hours pass through). The synthetic cost is only
    # internal to the helper and is never stored or returned.
    helper_proposal = proposal.model_copy(update={"allocable_cost_yen": 1})
    shared = calculate_shared(helper_proposal)
    candidate = None
    annual_pay: Decimal | None = None
    if pay is not None and days is not None and pay > 0 and days > 0:
        annual_pay = pay * days
    if not blockers and annual_pay is not None and multiplier is not None and denominator is not None:
        candidate = float(annual_pay * multiplier / denominator)

    result = shared.model_copy(deep=True)
    result.status = RateStatus.blocked if blockers else RateStatus.draft
    result.candidate_yen_per_person_hour = candidate
    result.denominator_person_hours = float(denominator) if denominator is not None else None
    result.u_period = float(u_period) if u_period is not None else None
    result.unknowns = sorted(set(blockers))
    basis: list[BasisRow] = []
    if pay is not None:
        basis.append(BasisRow(label="日給（入力）", value=float(pay), unit="円/日"))
    if days is not None:
        basis.append(BasisRow(label="年間支給日数（入力）", value=float(days), unit="日/年"))
    if annual_pay is not None:
        basis.append(BasisRow(label="年間給与換算額", value=float(annual_pay), unit="円/年"))
    if multiplier is not None:
        basis.append(BasisRow(label="工場で承認した給与倍率", value=float(multiplier), unit="倍"))
    if total_hours is not None:
        basis.append(BasisRow(label="期間総労働人時", value=float(total_hours), unit="人時/期間"))
    if u_period is not None:
        basis.append(BasisRow(label="期間請求可能割合 u_period", value=float(u_period), unit="割合"))
    if denominator is not None:
        basis.append(BasisRow(label="算定分母", value=float(denominator), unit="請求可能人時/期間"))
    basis.append(BasisRow(label="算定方式", value="給与倍率目安（正式原価式とは別の比較候補）", unit="方式"))
    if proposal.job_person_hours is not None:
        basis.append(BasisRow(label="案件時間基準", value=proposal.hours_basis.value if proposal.hours_basis else "未選択", unit="basis"))
    result.basis = basis
    return result
