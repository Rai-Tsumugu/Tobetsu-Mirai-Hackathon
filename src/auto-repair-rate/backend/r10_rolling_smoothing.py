"""R10 trailing 12-month cost smoothing using aggregate capacity."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _number(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def calculate_rolling_smoothing(*, monthly_cost_yen: list[Any], monthly_total_person_hours: list[Any],
                                monthly_u_period: list[Any], invoice_month: int,
                                seasonal_allocation_already_applied: bool) -> dict[str, Any]:
    blockers = []
    if not (len(monthly_cost_yen) == len(monthly_total_person_hours) == len(monthly_u_period) == 12):
        blockers.append("費用・人時・u_periodを直近12か月分入力してください")
    costs = [_number(value) for value in monthly_cost_yen]
    totals = [_number(value) for value in monthly_total_person_hours]
    ratios = [_number(value) for value in monthly_u_period]
    if any(value is None or value < 0 for value in costs): blockers.append("12か月すべての費用が既知の0以上である必要があります")
    if any(value is None or value <= 0 for value in totals): blockers.append("12か月すべての総労働人時が0より大きい必要があります")
    if any(value is None or value <= 0 or value > 1 for value in ratios): blockers.append("12か月すべてのu_periodが0より大きく1以下である必要があります")
    if invoice_month < 1 or invoice_month > 12: blockers.append("請求月は1〜12で指定してください")
    if seasonal_allocation_already_applied: blockers.append("季節配賦済み費用との二重計上を避けるため停止しました")
    billable = [t * u if t is not None and u is not None else None for t, u in zip(totals, ratios)]
    raw_rate = None
    if 1 <= invoice_month <= 12 and costs[invoice_month - 1] is not None and billable[invoice_month - 1] is not None and billable[invoice_month - 1] > 0:
        raw_rate = costs[invoice_month - 1] / billable[invoice_month - 1]
    smooth_rate = None
    total_cost = sum((value for value in costs if value is not None), Decimal(0))
    total_billable = sum((value for value in billable if value is not None), Decimal(0))
    if not blockers and total_billable > 0:
        smooth_rate = total_cost / total_billable
    return {"available": not blockers, "blockers": sorted(set(blockers)), "raw_invoice_month_rate": float(raw_rate) if raw_rate is not None else None,
            "smoothed_rate": float(smooth_rate) if smooth_rate is not None else None,
            "total_allocable_cost_yen": float(total_cost) if len(costs) == 12 and all(x is not None for x in costs) else None,
            "total_billable_hours": float(total_billable) if len(billable) == 12 and all(x is not None for x in billable) else None,
            "formula": "sum(cost[12 months]) / sum(total_hours[m] * u_period[m])"}
