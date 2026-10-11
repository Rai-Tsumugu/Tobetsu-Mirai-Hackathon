"""R06 period utilization scenario rate calculation."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _decimal(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def calculate_utilization_scenarios(*, allocable_cost_yen: Any,
                                    period_total_person_hours: Any,
                                    u_period_low: Any, u_period_mid: Any,
                                    u_period_high: Any,
                                    selected_scenario: str | None) -> dict[str, Any]:
    """Return all scenario rates; unknown required values withhold the candidate."""
    blockers: list[str] = []
    cost = _decimal(allocable_cost_yen, "allocable_cost_yen")
    total_hours = _decimal(period_total_person_hours, "period_total_person_hours")
    utilization = {
        "low": _decimal(u_period_low, "u_period_low"),
        "mid": _decimal(u_period_mid, "u_period_mid"),
        "high": _decimal(u_period_high, "u_period_high"),
    }
    if cost is None:
        blockers.append("期間配賦原価が未入力または数値ではありません")
    elif cost < 0 or cost != cost.to_integral_value():
        blockers.append("期間配賦原価は0以上の整数円で入力してください")
    if total_hours is None or total_hours <= 0:
        blockers.append("期間総労働人時は0より大きい値が必要です")
    for name, value in utilization.items():
        if value is None:
            blockers.append(f"u_period_{name} が不明です")
        elif value <= 0 or value > 1:
            blockers.append(f"u_period_{name} は0より大きく1以下の値が必要です")
    if all(value is not None for value in utilization.values()):
        if not utilization["low"] <= utilization["mid"] <= utilization["high"]:
            blockers.append("稼働率は low <= mid <= high の順にしてください")
    if selected_scenario not in {"low", "typical", "high"}:
        blockers.append("採用するシナリオを明示してください")

    denominators: dict[str, Decimal | None] = {"low": None, "typical": None, "high": None}
    rates: dict[str, Decimal | None] = {"low": None, "typical": None, "high": None}
    ratio_for_rate = {"low": "high", "typical": "mid", "high": "low"}
    if total_hours is not None and total_hours > 0:
        for rate_name, ratio_name in ratio_for_rate.items():
            ratio = utilization[ratio_name]
            if ratio is not None and 0 < ratio <= 1:
                denominator = total_hours * ratio
                denominators[rate_name] = denominator
                if denominator == 0:
                    blockers.append(f"{rate_name} シナリオの分母が0です")
                elif cost is not None and cost >= 0 and cost == cost.to_integral_value():
                    rates[rate_name] = cost / denominator

    if any(value is None for value in utilization.values()):
        blockers.append("不足する稼働率があるため3シナリオの比較を停止しました")
    if selected_scenario in rates and rates[selected_scenario] is None:
        blockers.append("選択したシナリオの分母または原価が不明のため候補を出せません")
    candidate = rates[selected_scenario] if selected_scenario in rates and not blockers else None
    return {
        "available": candidate is not None,
        "candidate_yen_per_person_hour": float(candidate) if candidate is not None else None,
        "selected_scenario": selected_scenario,
        "denominator_person_hours": (float(denominators[selected_scenario])
                                      if selected_scenario in denominators and denominators[selected_scenario] is not None else None),
        "scenario_rates": {key: float(value) if value is not None else None for key, value in rates.items()},
        "scenario_denominators": {key: float(value) if value is not None else None for key, value in denominators.items()},
        "blockers": sorted(set(blockers)),
        "formulas": {
            "low": "C / (H_period_total * u_period_high)",
            "typical": "C / (H_period_total * u_period_mid)",
            "high": "C / (H_period_total * u_period_low)",
        },
        "explanations": {
            "low": "期間費用と総労働人時を固定し、高い期間稼働率を使う低単価シナリオ",
            "typical": "期間費用と総労働人時を固定し、中間の期間稼働率を使う標準シナリオ",
            "high": "期間費用と総労働人時を固定し、低い期間稼働率を使う高単価シナリオ",
        },
    }
