"""R13 mobile cost cards normalized to annual values and evaluated by R01."""
from __future__ import annotations

from decimal import Decimal

from backend.r01_annual_cost import calculate_annual_cost


def normalize_cards(cards: list[dict], confirm_payroll_overlap: bool = False) -> dict:
    annual_costs = []
    blockers = []
    for card in cards:
        amount = card.get("amount")
        period = card["period"]
        included = card["include_flag"]
        category = card["category"]
        amount_annual = None if amount is None else float(Decimal(str(amount)) * (12 if period == "monthly" else 1))
        if category == "materials" and included:
            blockers.append("別請求の部品・材料費は労務原価に含められません")
        annual_costs.append({"id": category, "category": "materials" if category == "materials" else category,
                             "label": card["label"], "amount_yen": amount_annual,
                             "included_in_rate": included and category != "materials",
                             "status": "unknown" if amount_annual is None else card["status"],
                             "source": card.get("source"), "evidence": card.get("notes"),
                             "payroll_overlap": False, "payroll_overlap_confirmed": bool(confirm_payroll_overlap)})
    payroll_included = any(c.get("category") == "payroll" and c.get("include_flag") for c in cards)
    if payroll_included and not confirm_payroll_overlap:
        blockers.append("給与の重複計上がないことを人が確認してください")
    return {"annual_costs": annual_costs, "blockers": blockers}


def calculate_wizard(cards: list[dict], total_person_hours: float | None, u_period: float | None,
                     period_start: str, period_end: str, effective_from: str,
                     confirm_payroll_overlap: bool = False) -> dict:
    normalized = normalize_cards(cards, confirm_payroll_overlap)
    result = calculate_annual_cost({"period_label": "annualized from explicit monthly/annual entries",
        "period_start": period_start, "period_end": period_end, "effective_from": effective_from,
        "H_period_total": total_person_hours, "u_period": u_period,
        "costs": normalized["annual_costs"]})
    result["blockers"] = normalized["blockers"] + result["blockers"]
    if result["blockers"]:
        result["candidate_yen_per_person_hour"] = None
        result["candidate_status"] = "blocked"
        result["labor_rate_issued"] = False
    result["normalization"] = "monthly amount x 12; annual amount x 1"
    return result
