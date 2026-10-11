"""R05 cost-floor and mutually exclusive target-profit rate calculation."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _number(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a finite number") from None
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite number")
    return result


def calculate_cost_floor(*, allocable_cost_yen: Any, period_total_person_hours: Any,
                         u_period: Any, target_type: str | None, target_value: Any) -> dict[str, Any]:
    """Calculate cost and one selected profit target; unknown/zero inputs block."""
    blockers: list[str] = []
    cost = _number(allocable_cost_yen, "allocable_cost_yen")
    total_hours = _number(period_total_person_hours, "period_total_person_hours")
    utilization = _number(u_period, "u_period")
    target = _number(target_value, "target_value")
    if cost is None:
        blockers.append("配賦原価が不明です")
    elif cost < 0 or cost != cost.to_integral_value():
        blockers.append("配賦原価は0以上の整数円で入力してください")
    if total_hours is None or total_hours <= 0:
        blockers.append("期間総労働人時は0より大きい値が必要です")
    if utilization is None or utilization <= 0 or utilization > 1:
        blockers.append("u_period は0より大きく1以下の値が必要です")
    if target_type not in {"profit_amount", "profit_margin"}:
        blockers.append("目標利益は利益額または利益率のどちらか一方を選択してください")
    if target is None:
        blockers.append("目標利益の値が不明です")
    elif target < 0 or (target_type == "profit_margin" and target >= 1):
        blockers.append("目標利益額は0以上、目標利益率は0以上1未満で入力してください")
    denominator = total_hours * utilization if total_hours is not None and utilization is not None and total_hours > 0 and utilization > 0 else None
    if denominator == 0:
        blockers.append("請求可能人時が0のため試算できません")
    cost_rate = cost / denominator if cost is not None and denominator else None
    candidate = None
    if not blockers and cost_rate is not None and target is not None and denominator is not None:
        candidate = cost_rate + target / denominator if target_type == "profit_amount" else cost_rate / (1 - target)
    return {
        "available": candidate is not None,
        "cost_rate": float(cost_rate) if cost_rate is not None else None,
        "candidate_yen_per_person_hour": float(candidate) if candidate is not None else None,
        "denominator_person_hours": float(denominator) if denominator is not None else None,
        "blockers": blockers,
        "formula": "cost_rate + target_profit_yen / H_period_bill" if target_type == "profit_amount" else "cost_rate / (1 - target_profit_margin)",
    }
