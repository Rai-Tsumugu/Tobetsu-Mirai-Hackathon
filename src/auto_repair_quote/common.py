"""Shared validation and arithmetic for auto-repair quote implementations."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

BANDS = ("low", "typical", "high")


class QuoteError(ValueError):
    """Raised when quote input violates the shared data contract."""


def number(value: Any) -> Decimal:
    """Parse a finite, non-negative decimal value without binary float math."""
    if value is None or isinstance(value, bool):
        raise QuoteError("number must be a finite non-negative value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise QuoteError("number must be a finite non-negative value") from None
    if not result.is_finite() or result < 0:
        raise QuoteError("number must be a finite non-negative value")
    return result


def range_value(value: Mapping[str, Any]) -> dict[str, Decimal]:
    """Validate a complete, ordered low/typical/high range."""
    if not isinstance(value, Mapping) or set(value) != set(BANDS):
        raise QuoteError("range must contain exactly low, typical, and high")
    result = {band: number(value[band]) for band in BANDS}
    if not result["low"] <= result["typical"] <= result["high"]:
        raise QuoteError("range values must satisfy low <= typical <= high")
    return result


def _json_number(value: Decimal) -> int | float:
    """Convert a Decimal into a JSON-compatible finite number."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def money_range(value: Any) -> dict[str, int | float]:
    """Return a JSON-number range; a scalar is expanded to all three bands."""
    if isinstance(value, Mapping):
        parsed = range_value(value)
    else:
        scalar = number(value)
        parsed = {band: scalar for band in BANDS}
    return {band: _json_number(parsed[band]) for band in BANDS}


def add_ranges(*values: Any) -> dict[str, int | float]:
    """Add scalar or range operands independently at each band."""
    totals = {band: Decimal(0) for band in BANDS}
    for value in values:
        parsed = range_value(value) if isinstance(value, Mapping) else {
            band: number(value) for band in BANDS
        }
        for band in BANDS:
            totals[band] += parsed[band]
    return {band: _json_number(totals[band]) for band in BANDS}


def multiply_ranges(left: Any, right: Any) -> dict[str, int | float]:
    """Multiply scalar/range operands, pairing matching bands when both vary."""
    lhs = range_value(left) if isinstance(left, Mapping) else {
        band: number(left) for band in BANDS
    }
    rhs = range_value(right) if isinstance(right, Mapping) else {
        band: number(right) for band in BANDS
    }
    result = {band: lhs[band] * rhs[band] for band in BANDS}
    # Multiplication of two independently ordered ranges preserves ordering for
    # non-negative values, which number() guarantees.
    return {band: _json_number(result[band]) for band in BANDS}


def new_quote(labor: Mapping[str, Any], labor_rate: Mapping[str, Any], items: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Create an empty proposed quote with an immutable-by-copy input snapshot."""
    if not isinstance(labor, Mapping) or not isinstance(labor_rate, Mapping) or not isinstance(items, list):
        raise QuoteError("labor, labor_rate, and items must be mappings/list")
    return {
        "lines": [],
        "subtotal": money_range(0),
        "tax": money_range(0),
        "total": money_range(0),
        "reasons": [],
        "confirmed_by": None,
        "override_reason": None,
        "status": "proposed",
        "metadata": {"input_snapshot": deepcopy({
            "labor": labor,
            "labor_rate": labor_rate,
            "items": items,
        })},
    }


def make_line(
    *,
    line_id: str,
    kind: str,
    category: str | None,
    description: str,
    quantity_range: Mapping[str, Any],
    unit: str,
    unit_price_range: Mapping[str, Any],
    amount: Mapping[str, Any],
    source_system: str,
    source_ref: str | None,
    snapshot: Mapping[str, Any],
    reason: str,
    status: str = "proposed",
) -> dict[str, Any]:
    """Build a line with the canonical snake_case keys and JSON ranges."""
    return {
        "line_id": line_id,
        "kind": kind,
        "category": category,
        "description": description,
        "quantity_range": money_range(quantity_range),
        "unit": unit,
        "unit_price_range": money_range(unit_price_range),
        "amount": money_range(amount),
        "source_system": source_system,
        "source_ref": source_ref,
        "snapshot": deepcopy(dict(snapshot)),
        "reason": reason,
        "status": status,
    }
