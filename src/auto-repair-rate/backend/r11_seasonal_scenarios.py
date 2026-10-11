"""R11 independent cost and billable-hour scenario calculations."""
from __future__ import annotations

from typing import Any


def calculate_seasonal_scenarios(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for scenario in scenarios:
        name = scenario["name"]
        fixed = scenario.get("fixed_cost_yen")
        variable = scenario.get("variable_cost_yen")
        hours = scenario.get("H_period_bill")
        blockers = []
        if fixed is None or variable is None:
            blockers.append("費用額が不明")
        if hours is None:
            blockers.append("請求可能人時が不明")
        elif hours <= 0:
            blockers.append("請求可能人時は0より大きい値が必要")
        rate = (fixed + variable) / hours if not blockers else None
        period = scenario.get("period", "")
        assumptions = scenario.get("assumptions", "")
        basis = " / ".join(value for value in (period, assumptions) if value)
        results.append({"name": name, "rate_yen_per_person_hour": rate,
                        "available": rate is not None, "blockers": blockers,
                        "period": period, "assumptions": assumptions, "basis": basis})
    return {"formula": "(C_fixed + C_variable_s) / H_period_bill_s", "scenarios": results,
            "selected_scenario": None, "requires_human_scenario_choice": True}
