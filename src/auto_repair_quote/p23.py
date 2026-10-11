"""P23: compare quote amounts, line contributions, and stated conditions by band."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .common import BANDS, QuoteError


def compare_bands(quote: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return a read-only comparison of the quote's three price bands."""
    if not isinstance(quote, Mapping):
        raise QuoteError("quote must be an object")
    total = quote.get("total")
    if not isinstance(total, Mapping):
        raise QuoteError("quote.total must be an object")
    lines = quote.get("lines", [])
    conditions = quote.get("conditions", [])
    if not isinstance(lines, list):
        raise QuoteError("quote.lines must be a list")
    if not isinstance(conditions, list):
        raise QuoteError("quote.conditions must be a list")

    typical_total = _decimal_or_none(total.get("typical"), "quote.total.typical")
    comparisons = []
    for band in BANDS:
        amount = deepcopy(total.get(band))
        _decimal_or_none(amount, f"quote.total.{band}")
        for index, line in enumerate(lines):
            if not isinstance(line, Mapping):
                raise QuoteError(f"quote.lines.{index} must be an object")
            amounts = line.get("amount")
            if not isinstance(amounts, Mapping):
                raise QuoteError(f"quote.lines.{index}.amount must be an object")
            _decimal_or_none(amounts.get(band), f"quote.lines.{index}.amount.{band}")
            _decimal_or_none(amounts.get("typical"), f"quote.lines.{index}.amount.typical")
        contributions = []
        line_ids = []
        for line in lines:
            amounts = line["amount"]
            band_amount = amounts.get(band)
            typical_amount = amounts.get("typical")
            band_value = _decimal_or_none(band_amount, f"line.amount.{band}")
            typical_value = _decimal_or_none(typical_amount, "line.amount.typical")
            line_id = deepcopy(line.get("line_id"))
            line_ids.append(line_id)
            contributions.append({
                "line_id": line_id,
                "amount": deepcopy(band_amount),
                "typical_amount": deepcopy(typical_amount),
                "difference_from_typical": _json_number(band_value - typical_value)
                if band_value is not None and typical_value is not None else None,
                "source_ref": deepcopy(line.get("source_ref")),
            })

        matched_conditions = []
        for index, condition in enumerate(conditions):
            if not isinstance(condition, Mapping):
                raise QuoteError(f"quote.conditions.{index} must be an object")
            specified_bands = condition.get("bands", condition.get("band"))
            if specified_bands is None:
                applies = False
            else:
                if isinstance(specified_bands, str):
                    specified_bands = [specified_bands]
                if not isinstance(specified_bands, (list, tuple)) or any(item not in BANDS for item in specified_bands):
                    raise QuoteError(f"quote.conditions.{index}.bands is invalid")
                applies = band in specified_bands
            if applies:
                ref = condition.get("condition_ref", condition.get("source_ref", condition.get("id", index)))
                matched_conditions.append({"ref": deepcopy(ref), "condition": deepcopy(dict(condition))})

        band_total = _decimal_or_none(amount, f"quote.total.{band}")
        delta = None if band_total is None or typical_total is None else band_total != typical_total
        comparisons.append({
            "band": band,
            "amount": amount,
            "condition_refs": [item["ref"] for item in matched_conditions],
            "conditions": [item["condition"] for item in matched_conditions],
            "line_ids": line_ids,
            "contributions": contributions,
            "explanation_status": "explained" if matched_conditions or delta is False else "unexplained",
        })
    return comparisons


def _decimal_or_none(value: Any, path: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise QuoteError(f"{path} must be a finite non-negative amount or null")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise QuoteError(f"{path} must be a finite non-negative amount or null") from None
    if not parsed.is_finite() or parsed < 0:
        raise QuoteError(f"{path} must be a finite non-negative amount or null")
    return parsed


def _json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)
