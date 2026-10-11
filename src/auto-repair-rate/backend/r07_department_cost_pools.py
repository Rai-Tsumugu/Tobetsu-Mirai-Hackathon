"""R07 department labor-pool allocation and rate calculations."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

CATEGORIES = ("整備", "鈑金塗装")


def _number(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def calculate_department_rates(*, direct_cost_yen: dict[str, Any], shared_cost_yen: Any,
                               allocation_key: dict[str, Any], total_person_hours: dict[str, Any],
                               u_period: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    parsed_direct = {category: _number(direct_cost_yen.get(category)) for category in CATEGORIES}
    parsed_key = {category: _number(allocation_key.get(category)) for category in CATEGORIES}
    parsed_hours = {category: _number(total_person_hours.get(category)) for category in CATEGORIES}
    parsed_u = {category: _number(u_period.get(category)) for category in CATEGORIES}
    common = _number(shared_cost_yen)
    if common is None or common < 0:
        blockers.append("共通費が未入力または0以上の金額ではありません")
    if any(value is None or value < 0 for value in parsed_direct.values()):
        blockers.append("2カテゴリの個別費用が必要です")
    if any(value is None or value < 0 for value in parsed_key.values()):
        blockers.append("配賦キーが必要です")
    elif sum(parsed_key.values(), Decimal(0)) <= 0:
        blockers.append("配賦キー合計は0より大きい必要があります")
    if any(value is None or value <= 0 for value in parsed_hours.values()):
        blockers.append("各カテゴリの総労働人時は0より大きい値が必要です")
    if any(value is None or value <= 0 or value > 1 for value in parsed_u.values()):
        blockers.append("各カテゴリのu_periodは0より大きく1以下の値が必要です")
    allocated: dict[str, Decimal | None] = {category: None for category in CATEGORIES}
    if common is not None and common >= 0 and not any(v is None or v < 0 for v in parsed_key.values()) and sum(parsed_key.values(), Decimal(0)) > 0:
        total_key = sum(parsed_key.values(), Decimal(0))
        # Allocate to cents, then assign the exact rounding remainder to the last category.
        first = (common * parsed_key[CATEGORIES[0]] / total_key).quantize(Decimal("0.01"))
        allocated[CATEGORIES[0]] = first
        allocated[CATEGORIES[1]] = common - first
    category_costs: dict[str, Decimal | None] = {}
    rates: dict[str, Decimal | None] = {}
    denominators: dict[str, Decimal | None] = {}
    for category in CATEGORIES:
        direct = parsed_direct[category]
        alloc = allocated[category]
        hours, utilization = parsed_hours[category], parsed_u[category]
        category_costs[category] = direct + alloc if direct is not None and alloc is not None else None
        denominators[category] = hours * utilization if hours is not None and utilization is not None else None
        if denominators[category] is not None and denominators[category] <= 0:
            blockers.append(f"{category}の請求可能人時が0です")
        if category_costs[category] is not None and denominators[category] is not None and denominators[category] > 0:
            rates[category] = category_costs[category] / denominators[category]
        else:
            rates[category] = None
    reconciliation = (sum((v for v in allocated.values() if v is not None), Decimal(0)) == common) if common is not None else False
    if not reconciliation:
        blockers.append("共通費の配賦合計が元金額と一致しません")
    return {
        "available": not blockers, "blockers": sorted(set(blockers)),
        "categories": list(CATEGORIES), "allocated_shared_cost_yen": {k: float(v) if v is not None else None for k, v in allocated.items()},
        "category_cost_yen": {k: float(v) if v is not None else None for k, v in category_costs.items()},
        "denominator_billable_hours": {k: float(v) if v is not None else None for k, v in denominators.items()},
        "rate_yen_per_person_hour": {k: float(v) if v is not None else None for k, v in rates.items()},
        "source_shared_cost_yen": float(common) if common is not None else None,
        "reconciled_shared_cost_yen": float(sum((v for v in allocated.values() if v is not None), Decimal(0))),
        "reconciles": reconciliation,
    }
