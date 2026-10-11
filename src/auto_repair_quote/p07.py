"""P07: group quote rows by cost category and calculate banded subtotals."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .common import BANDS, QuoteError, _json_number

_KINDS = {"labor", "parts", "materials", "adjustment", "discount"}
_MATERIAL_CATEGORIES = {"塗料", "溶剤", "消耗品"}
_GROUPS = ("labor", "parts", "materials", "adjustments")


def apply(quote: dict[str, Any], inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a deep-copied quote with validated category and total ranges.

    Inputs are accepted for compatibility with the quote pipeline; P07 derives
    its result exclusively from the quote's line snapshots.
    """
    if not isinstance(quote, dict):
        raise QuoteError("quote must be an object")
    if inputs is not None and not isinstance(inputs, dict):
        raise QuoteError("inputs must be an object when provided")
    lines = quote.get("lines")
    if not isinstance(lines, list):
        raise QuoteError("quote.lines must be a list")

    seen: set[str] = set()
    totals = {group: {band: Decimal(0) for band in BANDS} for group in _GROUPS}
    for index, line in enumerate(lines):
        if not isinstance(line, Mapping):
            raise QuoteError(f"quote.lines.{index} must be an object")
        line_id = line.get("line_id")
        if not isinstance(line_id, (str, int)) or isinstance(line_id, bool) or not str(line_id).strip():
            raise QuoteError(f"quote.lines.{index}.line_id is required")
        line_id = str(line_id)
        if line_id in seen:
            raise QuoteError(f"duplicate line_id: {line_id}")
        seen.add(line_id)

        kind = line.get("kind")
        if kind not in _KINDS:
            raise QuoteError(f"quote.lines.{index}.kind is unknown")
        group = _validate_category(kind, line.get("category"), index)
        amount = _amount_range(
            line.get("amount"), index, allow_negative=(kind == "discount"),
            allow_unordered=(kind in {"adjustment", "discount"}),
        )
        for band in BANDS:
            totals[group][band] += amount[band]

    subtotal = {band: sum((totals[group][band] for group in _GROUPS), Decimal(0)) for band in BANDS}
    for band, amount in subtotal.items():
        if amount < 0:
            raise QuoteError(f"subtotal.{band} must not be negative after discounts")
    if not subtotal["low"] <= subtotal["typical"] <= subtotal["high"]:
        raise QuoteError("subtotal bands must satisfy low <= typical <= high")

    result = deepcopy(quote)
    result["labor_subtotal"] = _json_range(totals["labor"])
    result["parts_subtotal"] = _json_range(totals["parts"])
    result["materials_subtotal"] = _json_range(totals["materials"])
    result["adjustments_subtotal"] = _json_range(totals["adjustments"])
    result["subtotal"] = _json_range(subtotal)
    return result


def group_lines(quote: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return categorized line collections and subtotals for UI cards."""
    calculated = apply(dict(quote))
    groups: dict[str, dict[str, Any]] = {
        "labor": {"lines": [], "subtotal": calculated["labor_subtotal"]},
        "parts": {"lines": [], "subtotal": calculated["parts_subtotal"]},
        "materials": {"lines": [], "subtotal": calculated["materials_subtotal"]},
        "adjustments": {"lines": [], "subtotal": calculated["adjustments_subtotal"]},
    }
    for line in calculated["lines"]:
        kind = line["kind"]
        group = "adjustments" if kind in ("adjustment", "discount") else kind
        groups[group]["lines"].append(deepcopy(line))
    return groups


def _validate_category(kind: str, category: Any, index: int) -> str:
    error = f"quote.lines.{index}.category does not match kind {kind}"
    if kind == "labor" and category == "labor":
        return "labor"
    if kind == "parts" and category == "部品":
        return "parts"
    if kind == "materials" and category in _MATERIAL_CATEGORIES:
        return "materials"
    if kind == "adjustment" and category in {"labor", "subtotal"}:
        # Scope describes which base the rule considered, not another cost
        # bucket. The adjustment amount is counted once in its own bucket.
        return "adjustments"
    if kind == "discount" and category is None:
        return "adjustments"
    raise QuoteError(error)


def _amount_range(
    value: Any, index: int, *, allow_negative: bool, allow_unordered: bool,
) -> dict[str, Decimal]:
    label = f"quote.lines.{index}.amount"
    if isinstance(value, Mapping) and set(value) == set(BANDS):
        raw_values = value
    elif not isinstance(value, Mapping) and value is not None:
        raw_values = {band: value for band in BANDS}
    else:
        raise QuoteError(f"{label} must contain low, typical, and high")
    parsed: dict[str, Decimal] = {}
    for band in BANDS:
        raw = raw_values[band]
        if raw is None or isinstance(raw, bool):
            raise QuoteError(f"{label}.{band} must be finite")
        try:
            number = Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            raise QuoteError(f"{label}.{band} must be finite") from None
        if not number.is_finite() or (number < 0 and not allow_negative):
            raise QuoteError(f"{label}.{band} must be finite and non-negative")
        parsed[band] = number
    # Discounts are signed reductions and their values may reverse band order.
    if not allow_unordered and not parsed["low"] <= parsed["typical"] <= parsed["high"]:
        raise QuoteError(f"{label} bands must satisfy low <= typical <= high")
    return parsed


def _json_range(values: Mapping[str, Decimal]) -> dict[str, int | float]:
    result = {band: _json_number(values[band]) for band in BANDS}
    # Decimal-to-float conversion can overflow even when the Decimal is finite.
    for value in result.values():
        if isinstance(value, float) and not Decimal(str(value)).is_finite():
            raise QuoteError("subtotal must be finite")
    return result
