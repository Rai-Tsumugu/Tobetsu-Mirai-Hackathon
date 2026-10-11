"""R08 annualize heating and other allocable costs over the full year."""
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


def calculate_annual_heating_rate(*, annual_heating_cost_yen: Any, other_allocable_cost_yen: Any,
                                  annual_billable_hours: Any) -> dict[str, Any]:
    heating, other, hours = map(_number, (annual_heating_cost_yen, other_allocable_cost_yen, annual_billable_hours))
    blockers = []
    if heating is None or heating < 0: blockers.append("暖房年額が未入力または0以上ではありません")
    if other is None or other < 0: blockers.append("その他の年間配賦費用が未入力または0以上ではありません")
    if hours is None or hours <= 0: blockers.append("年間請求可能人時は0より大きい値が必要です")
    heating_rate = heating / hours if heating is not None and hours is not None and hours > 0 else None
    base_rate = other / hours if other is not None and hours is not None and hours > 0 else None
    rate = heating_rate + base_rate if heating_rate is not None and base_rate is not None else None
    return {"available": not blockers, "blockers": blockers, "annual_heating_rate": float(heating_rate) if heating_rate is not None else None,
            "annual_base_rate": float(base_rate) if base_rate is not None else None,
            "candidate_yen_per_person_hour": float(rate) if rate is not None else None,
            "annual_billable_hours": float(hours) if hours is not None else None,
            "annual_allocable_cost_yen": float(heating + other) if heating is not None and other is not None else None}
