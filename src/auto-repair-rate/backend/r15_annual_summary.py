"""R15 annual aggregate cost rate calculation."""

def calculate_annual_summary(allocable_cost_yen, H_period_total, u_period, materials_excluded):
    blockers = []
    if allocable_cost_yen is None: blockers.append("配賦費用合計が不明です")
    if H_period_total is None: blockers.append("期間総労働人時が不明です")
    if u_period is None: blockers.append("期間請求可能割合 u_period が不明です")
    if not materials_excluded: blockers.append("別請求の部品・材料を除外した確認が必要です")
    denominator = H_period_total * u_period if H_period_total is not None and u_period is not None else None
    if denominator is not None and denominator <= 0: blockers.append("請求可能人時が0のため停止しました")
    return {"candidate_yen_per_person_hour": allocable_cost_yen / denominator if not blockers else None,
            "denominator_person_hours": denominator, "blockers": blockers,
            "formula": "allocable_cost_yen / (H_period_total * u_period)"}
