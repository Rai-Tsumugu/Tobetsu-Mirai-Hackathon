"""R12 append-only cost change history and as-of calculations."""
from __future__ import annotations

from datetime import date
from typing import Any


def calculate_as_of(base_costs: dict[str, float | None], events: list[dict[str, Any]], as_of: date,
                    H_period_bill: float | None) -> dict[str, Any]:
    values = dict(base_costs)
    applied = []
    blockers = []
    baselines: dict[str, float] = {}
    for event in sorted(events, key=lambda row: (row["effective_from"], row["event_id"])):
        effective = date.fromisoformat(event["effective_from"])
        category = event["category"]
        if effective > as_of:
            continue
        # Legacy callers without an old value cannot establish a trustworthy base.
        if "old_amount_yen" not in event:
            blockers.append(f"{category}: 変更前金額の根拠がなく適用できません")
            baselines[category] = None
            continue
        if category not in baselines:
            base = values.get(category)
            old = event.get("old_amount_yen")
            if base is None or old is None:
                blockers.append(f"{category}: 適用前の費用基準額が不明")
                baselines[category] = None
                continue
            if float(base) != float(old):
                blockers.append(f"{category}: 最初の変更前金額が基準費用と一致しません")
                baselines[category] = None
                continue
            baselines[category] = float(base)
        elif baselines[category] is None:
            continue
        elif event.get("old_amount_yen") is None or float(event["old_amount_yen"]) != float(values[category]):
            blockers.append(f"{category}: 変更前金額が直前の費用額と一致しません")
            baselines[category] = None
            continue
        values[category] = event["new_amount_yen"]
        applied.append(event)
    excluded_labels = {"materials", "material", "parts", "part", "材料", "部品", "部品・材料", "separately_billed_materials"}
    allocable_values = {category: amount for category, amount in values.items() if category.strip().lower() not in excluded_labels}
    excluded_values = {category: amount for category, amount in values.items() if category.strip().lower() in excluded_labels}
    if any(amount is None for amount in allocable_values.values()):
        blockers.append("費用額が不明")
    if H_period_bill is None:
        blockers.append("請求可能人時が不明")
    elif H_period_bill <= 0:
        blockers.append("請求可能人時は0より大きい値が必要")
    total = sum(allocable_values.values()) if not blockers else None
    rate = total / H_period_bill if total is not None and H_period_bill else None
    return {"as_of": as_of.isoformat(), "costs_as_of_yen": values, "allocable_costs_as_of_yen": allocable_values,
            "excluded_materials_as_of_yen": excluded_values, "total_cost_yen": total,
            "H_period_bill": H_period_bill, "candidate_yen_per_person_hour": rate,
            "applied_event_ids": [e["event_id"] for e in applied], "blockers": blockers,
            "formula": "sum(base costs reconciled with effective cost events on or before as_of) / H_period_bill",
            "period_semantics": f"cost amounts for the period ending {as_of.isoformat()}"}
