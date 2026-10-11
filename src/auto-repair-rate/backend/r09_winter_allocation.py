"""R09 winter-only cost scenario with explicit baseline and policy gate."""
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


def calculate_winter_scenario(*, winter_cost_yen: Any, winter_billable_hours: Any,
                              annual_baseline_rate: Any, annual_billable_hours: Any,
                              price_policy_confirmed: bool) -> dict[str, Any]:
    cost, winter_hours, baseline, annual_hours = map(_number, (winter_cost_yen, winter_billable_hours, annual_baseline_rate, annual_billable_hours))
    common_blockers = []
    winter_blockers = []
    if baseline is None or baseline <= 0: common_blockers.append("明示された年間基準単価が必要です")
    if annual_hours is None or annual_hours <= 0: common_blockers.append("年間請求可能人時は0より大きい値が必要です")
    if cost is None or cost < 0: winter_blockers.append("冬季費用が未入力または0以上ではありません")
    if winter_hours is None or winter_hours <= 0: winter_blockers.append("冬季請求可能人時は0より大きい値が必要です")
    winter_cost_rate = cost / winter_hours if cost is not None and winter_hours is not None and winter_hours > 0 else None
    winter_rate = baseline + winter_cost_rate if winter_cost_rate is not None and baseline is not None else None
    delta = winter_rate - baseline if winter_rate is not None and baseline is not None else None
    annual_impact = delta * winter_hours if delta is not None and winter_hours is not None else None
    blockers = sorted(set(common_blockers + winter_blockers + ([] if price_policy_confirmed else ["冬季価格方針を確認してください"])))
    return {"available": not common_blockers, "baseline_available": not common_blockers,
            "winter_available": not common_blockers and not winter_blockers,
            "blockers": blockers, "common_blockers": common_blockers, "winter_blockers": winter_blockers,
            "winter_cost_rate": float(winter_cost_rate) if winter_cost_rate is not None else None,
            "annual_baseline_rate": float(baseline) if baseline is not None else None,
            "winter_candidate_rate": float(winter_rate) if winter_rate is not None else None,
            "delta_yen_per_person_hour": float(delta) if delta is not None else None,
            "annual_impact_yen": float(annual_impact) if annual_impact is not None else None,
            "applied_by_default": False, "price_policy_confirmed": price_policy_confirmed}
