"""R17 compare paid wages with a separately imputed family-labor basis."""
def calculate_family_labor(paid_wages_yen, family_hours, shadow_cost_rate_yen, H_period_bill):
    blockers = []
    for name, value in (("実支払給与", paid_wages_yen), ("請求可能人時", H_period_bill)):
        if value is None: blockers.append(f"{name}が不明です")
    if family_hours is None: blockers.append("家族労働時間が不明です")
    if family_hours and shadow_cost_rate_yen is None: blockers.append("家族労務の仮原価率が不明です")
    if H_period_bill is not None and H_period_bill <= 0: blockers.append("請求可能人時が0のため停止しました")
    shadow = family_hours * shadow_cost_rate_yen if family_hours is not None and shadow_cost_rate_yen is not None else None
    paid_candidate = paid_wages_yen / H_period_bill if not blockers and paid_wages_yen is not None and H_period_bill else None
    with_family = (paid_wages_yen + shadow) / H_period_bill if not blockers and shadow is not None and H_period_bill else None
    return {"paid_only_yen_per_person_hour": paid_candidate, "with_family_yen_per_person_hour": with_family,
            "family_shadow_cost_yen": shadow, "blockers": blockers}
