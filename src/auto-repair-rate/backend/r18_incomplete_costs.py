"""R18 known-cost lower bound and explicitly assumed cost range."""
def calculate_incomplete_costs(known_cost_yen, unknown_items, H_period_bill, accept_uncertainty, materials_excluded=False):
    blockers = []
    if known_cost_yen is None: blockers.append("確認済み費用合計が不明です")
    if H_period_bill is None: blockers.append("請求可能人時が不明です")
    if H_period_bill is not None and H_period_bill <= 0: blockers.append("請求可能人時が0のため停止しました")
    missing = [item for item in unknown_items if item["upper_yen"] is None or item["lower_yen"] is None]
    if missing: blockers.append("不明費用の範囲が未入力です。未知額を0とは扱えません")
    if unknown_items and not accept_uncertainty: blockers.append("不確実性を理解したうえでの明示的な受け入れが必要です")
    if not materials_excluded: blockers.append("別請求の部品・材料を費用合計から除外した確認が必要です")
    if blockers: return {"lower_candidate": None, "upper_candidate": None, "known_lower_bound": None, "blockers": blockers, "provisional": bool(unknown_items)}
    lower_cost = known_cost_yen + sum(item["lower_yen"] for item in unknown_items)
    upper_cost = known_cost_yen + sum(item["upper_yen"] for item in unknown_items)
    return {"lower_candidate": lower_cost / H_period_bill, "upper_candidate": upper_cost / H_period_bill,
            "known_lower_bound": known_cost_yen / H_period_bill if unknown_items else None,
            "lower_cost_yen": lower_cost, "upper_cost_yen": upper_cost, "blockers": [],
            "provisional": bool(unknown_items)}
