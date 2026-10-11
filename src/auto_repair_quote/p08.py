"""P08: derive low/typical/high quote cards with their conditions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .common import BANDS, QuoteError


def band_cards(quote: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build display cards from a quote snapshot without changing its values."""
    if not isinstance(quote, Mapping):
        raise QuoteError("quote must be an object")
    total = quote.get("total")
    if not isinstance(total, Mapping):
        raise QuoteError("quote.total must be an object")
    conditions = quote.get("conditions", [])
    if not isinstance(conditions, list):
        raise QuoteError("quote.conditions must be a list")

    selected_band = quote.get("selected_band")
    if selected_band is not None and selected_band not in BANDS:
        raise QuoteError("quote.selected_band is unknown")
    quote_status = quote.get("status")

    cards = []
    for band in BANDS:
        amount = total.get(band)
        if amount is not None and (isinstance(amount, bool) or not _finite_nonnegative(amount)):
            raise QuoteError(f"quote.total.{band} must be finite and non-negative")

        matching = []
        for index, condition in enumerate(conditions):
            if not isinstance(condition, Mapping):
                raise QuoteError(f"quote.conditions.{index} must be an object")
            specified_bands = condition.get("bands", condition.get("band"))
            if specified_bands is None:
                applies = True
            else:
                if isinstance(specified_bands, str):
                    specified_bands = [specified_bands]
                if not isinstance(specified_bands, (list, tuple)) or any(item not in BANDS for item in specified_bands):
                    raise QuoteError(f"quote.conditions.{index}.bands is invalid")
                applies = band in specified_bands
            if applies:
                ref = condition.get("condition_ref", condition.get("source_ref", condition.get("id", index)))
                matching.append({"ref": deepcopy(ref), "condition": deepcopy(dict(condition))})

        blocked = quote_status == "blocked"
        cards.append({
            "band": band,
            "amount": deepcopy(amount),
            "condition_refs": [item["ref"] for item in matching],
            "conditions": [item["condition"] for item in matching],
            "selected": selected_band == band and amount is not None and not blocked,
            "status": "blocked" if blocked else ("unconfirmed" if amount is None else "available"),
            "label": "確定不可" if blocked else ("未確認" if amount is None else band),
        })
    return cards


def apply(quote: dict[str, Any], inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a deep-copied quote with display cards and an optional explicit choice."""
    if not isinstance(quote, dict):
        raise QuoteError("quote must be an object")
    if inputs is not None and not isinstance(inputs, dict):
        raise QuoteError("inputs must be an object when provided")
    result = deepcopy(quote)
    if result.get("status") == "blocked":
        result["selected_band"] = None
    selected_band = inputs.get("selected_band") if inputs is not None else None
    if selected_band is not None:
        if selected_band not in BANDS:
            raise QuoteError("inputs.selected_band is unknown")
        total = result.get("total")
        if not isinstance(total, Mapping) or selected_band not in total:
            raise QuoteError("selected band amount is unavailable")
        if total[selected_band] is None:
            raise QuoteError("selected band amount is unconfirmed")
        if result.get("status") == "blocked":
            raise QuoteError("blocked quote cannot select a final amount")
        result["selected_band"] = selected_band
    result["band_cards"] = band_cards(result)
    return result


def _finite_nonnegative(value: Any) -> bool:
    try:
        from decimal import Decimal, InvalidOperation

        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return False
    return parsed.is_finite() and parsed >= 0
