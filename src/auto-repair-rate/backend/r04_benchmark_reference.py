"""R04 manually entered benchmark references, never factory rate candidates."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from backend.models import BasisRow


@dataclass(frozen=True)
class BenchmarkInput:
    amount: Any
    currency: str
    amount_type: str
    hours_basis: str | None
    documented_person_hours: Any | None
    permission_status: str
    source_url: str | None = None
    source_text: str | None = None
    conditions: str | None = None


@dataclass(frozen=True)
class BenchmarkResult:
    available: bool
    reference_yen_per_person_hour: float | None
    reason: str | None
    basis: tuple[BasisRow, ...]


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def calculate_benchmark(data: BenchmarkInput | dict[str, Any]) -> BenchmarkResult:
    """Convert only explicitly labor-only, documented yen/person-hour data.

    References with unclear scope, hours, permission, or currency remain visible
    as records but cannot become a comparable numerical value.
    """
    if isinstance(data, dict):
        accepted_fields = BenchmarkInput.__dataclass_fields__
        data = BenchmarkInput(**{key: value for key, value in data.items() if key in accepted_fields})
    amount = _decimal(data.amount)
    hours = _decimal(data.documented_person_hours)
    reason = None
    if data.permission_status != "verified":
        reason = "利用条件・掲載許諾が確認できていません"
    elif data.currency != "JPY":
        reason = "円以外の金額は換算レートを確認できないため比較できません"
    elif data.amount_type != "labor_only":
        reason = "総額または労務のみと確認できない金額は比較できません"
    elif data.hours_basis != "documented_person_hours" or hours is None or hours <= 0:
        reason = "対象作業の正の人時が資料で確認できません"
    elif amount is None or amount <= 0:
        reason = "金額は0より大きい有限値で入力してください"
    rate = float(amount / hours) if reason is None and amount is not None and hours is not None else None
    basis = (
        BasisRow(label="外部比較値の状態", value="比較可能" if rate is not None else "参考不可", unit="状態"),
        BasisRow(label="比較元の金額", value=float(amount) if amount is not None else None, unit=data.currency),
        BasisRow(label="資料記載の対象人時", value=float(hours) if hours is not None else None, unit="人時"),
        BasisRow(label="外部参照値", value=rate, unit="円/人時"),
    )
    return BenchmarkResult(rate is not None, rate, reason, basis)
