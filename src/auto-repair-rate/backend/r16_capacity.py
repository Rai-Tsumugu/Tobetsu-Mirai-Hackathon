"""R16 role-based planned period person-hour aggregation."""
from decimal import Decimal

def calculate_capacity(roles, u_period):
    total = sum((Decimal(str(row["weekly_hours"])) * Decimal(str(row["work_weeks"])) for row in roles), Decimal(0))
    blockers = []
    if not roles: blockers.append("役割別の人員・時間入力がありません")
    if u_period is None: blockers.append("請求可能割合 u_period が不明です")
    billable = total * Decimal(str(u_period)) if u_period is not None else None
    if billable is not None and billable <= 0: blockers.append("請求可能人時が0のため停止しました")
    return {"period_total_person_hours": float(total), "billable_person_hours": float(billable) if billable is not None else None,
            "u_period": u_period, "blockers": blockers,
            "formula": "sum(weekly_hours * work_weeks); billable = total * u_period"}
