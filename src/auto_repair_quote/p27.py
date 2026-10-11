"""P27: persist an immutable snapshot when a quote is confirmed."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from .common import BANDS, QuoteError, number, range_value
from .p07 import apply as validate_lines_and_subtotal


def save_snapshot(store: Any, quote: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and atomically save a confirmed quote without changing it."""
    if not isinstance(quote, Mapping):
        raise QuoteError("quote must be an object")
    if quote.get("status") != "confirmed":
        raise QuoteError("only confirmed quotes can be snapshotted")
    quote_id = quote.get("quote_id")
    version = quote.get("quote_version")
    if not isinstance(quote_id, str) or not quote_id.strip():
        raise QuoteError("quote_id is required")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise QuoteError("quote_version must be a positive integer")
    if quote.get("selected_band") not in BANDS:
        raise QuoteError("selected_band must be low, typical, or high")
    confirmed_by = quote.get("confirmed_by")
    if not isinstance(confirmed_by, str) or not confirmed_by.strip():
        raise QuoteError("confirmed_by is required")
    confirmation = quote.get("confirmation")
    if not isinstance(confirmation, Mapping):
        raise QuoteError("confirmation is required")
    if confirmation.get("selected_band") != quote.get("selected_band"):
        raise QuoteError("confirmation.selected_band must match selected_band")
    if confirmation.get("confirmed_by") != confirmed_by:
        raise QuoteError("confirmation.confirmed_by must match confirmed_by")
    confirmed_at = quote.get("confirmed_at")
    confirmation_at = confirmation.get("confirmed_at")
    if not _nonempty(confirmed_at) or not _nonempty(confirmation_at):
        raise QuoteError("confirmed_at is required in quote and confirmation")
    if not _timestamps_consistent(confirmed_at, confirmation_at):
        raise QuoteError("confirmation.confirmed_at must match confirmed_at")
    if "final_amount" not in quote or "final_amount" not in confirmation:
        raise QuoteError("final_amount is required in quote and confirmation")
    if number(quote["final_amount"]) != number(confirmation["final_amount"]):
        raise QuoteError("confirmation.final_amount must match final_amount")
    if quote.get("override_reason") != confirmation.get("override_reason"):
        raise QuoteError("confirmation.override_reason must match override_reason")

    metadata = quote.get("metadata")
    inputs = metadata.get("input_snapshot") if isinstance(metadata, Mapping) else None
    if not isinstance(inputs, Mapping):
        raise QuoteError("metadata.input_snapshot is required")
    if not all(key in inputs for key in ("labor", "labor_rate", "items")):
        raise QuoteError("input snapshot must include labor, labor_rate, and items")
    if not isinstance(inputs["labor"], Mapping) or not isinstance(inputs["labor_rate"], Mapping) or not isinstance(inputs["items"], list):
        raise QuoteError("input snapshot labor/rate/items have invalid types")
    _validate_finite_numbers(inputs, "metadata.input_snapshot")

    lines = quote.get("lines")
    if not isinstance(lines, list):
        raise QuoteError("quote.lines must be a list")
    for index, line in enumerate(lines):
        if not isinstance(line, Mapping):
            raise QuoteError(f"quote.lines.{index} must be an object")
        if not _nonempty(line.get("source_system")) or not _nonempty(line.get("source_ref")):
            raise QuoteError(f"quote.lines.{index} source_system and source_ref are required")
        if not isinstance(line.get("snapshot"), Mapping) or not line["snapshot"]:
            raise QuoteError(f"quote.lines.{index}.snapshot is required")
        _band_range(line.get("quantity_range"), f"quote.lines.{index}.quantity_range")
        if "unit_price_range" in line:
            _unit_price_range(line["unit_price_range"], f"quote.lines.{index}.unit_price_range",
                              ordered=(line.get("kind") != "adjustment"))

    # P07 owns kind-aware amount validation: discounts may be negative and
    # adjustment/discount bands may be unordered. It also recomputes subtotal.
    validated = validate_lines_and_subtotal(dict(quote))
    subtotal = _band_range(quote.get("subtotal"), "subtotal")
    calculated_subtotal = _band_range(validated.get("subtotal"), "calculated subtotal")
    if subtotal != calculated_subtotal:
        raise QuoteError("subtotal must match line amounts")
    for field in ("labor_subtotal", "parts_subtotal", "materials_subtotal", "adjustments_subtotal"):
        if field in quote:
            provided = quote[field]
            if not isinstance(provided, Mapping) or set(provided) != set(BANDS):
                raise QuoteError(f"{field} must contain all bands")
            for band in BANDS:
                if isinstance(provided[band], bool):
                    raise QuoteError(f"{field} contains invalid values")
                try:
                    value = Decimal(str(provided[band]))
                except Exception:
                    raise QuoteError(f"{field} contains invalid values") from None
                if not value.is_finite() or value != Decimal(str(validated[field][band])):
                    raise QuoteError(f"{field} must match categorized line amounts")
    tax = _band_range(quote.get("tax"), "tax")
    total = _band_range(quote.get("total"), "total")
    for band in BANDS:
        if subtotal[band] + tax[band] != total[band]:
            raise QuoteError(f"total.{band} must equal subtotal plus tax")

    final_amount = quote["final_amount"]
    if final_amount is not None:
        amount = number(final_amount)
        if amount != total[quote["selected_band"]] and not _nonempty(quote.get("override_reason")):
            nested_reason = confirmation.get("override_reason") if isinstance(confirmation, Mapping) else None
            if not _nonempty(nested_reason):
                raise QuoteError("a changed final_amount requires override_reason")

    saved = deepcopy(dict(quote))
    saved["inputs"] = deepcopy(dict(inputs))
    saved["subtotals"] = {
        key: deepcopy(value) for key, value in saved.items()
        if key.endswith("_subtotal")
    }
    # Keep the canonical subtotal alongside any category subtotals.
    saved["subtotals"]["subtotal"] = deepcopy(quote["subtotal"])
    with store.transaction():
        store.save_quote(saved)
    return deepcopy(saved)


def load_snapshot(store: Any, quote_id: str, quote_version: int | None = None) -> dict[str, Any]:
    """Load a persisted quote version as an isolated copy."""
    if quote_version is not None and (isinstance(quote_version, bool) or not isinstance(quote_version, int) or quote_version < 1):
        raise QuoteError("quote_version must be a positive integer")
    return deepcopy(store.get_quote(quote_id, quote_version))


def _band_range(value: Any, path: str) -> dict[str, Decimal]:
    try:
        return range_value(value)
    except (QuoteError, TypeError) as exc:
        raise QuoteError(f"{path} must contain finite low, typical, and high values") from exc


def _unit_price_range(value: Any, path: str, *, ordered: bool) -> dict[str, Decimal]:
    if not isinstance(value, Mapping) or set(value) != set(BANDS):
        raise QuoteError(f"{path} must contain low, typical, and high")
    parsed = {band: number(value[band]) for band in BANDS}
    if ordered and not parsed["low"] <= parsed["typical"] <= parsed["high"]:
        raise QuoteError(f"{path} bands must be ordered")
    return parsed


def _validate_finite_numbers(value: Any, path: str) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float, Decimal)):
        try:
            finite = Decimal(str(value)).is_finite()
        except Exception:
            finite = False
        if not finite:
            raise QuoteError(f"{path} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_finite_numbers(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_finite_numbers(item, f"{path}.{index}")

def _timestamps_consistent(left: str, right: str) -> bool:
    try:
        left_dt = datetime.fromisoformat(left.replace("Z", "+00:00"))
        right_dt = datetime.fromisoformat(right.replace("Z", "+00:00"))
    except ValueError:
        return False
    if left_dt.tzinfo is None or right_dt.tzinfo is None:
        return False
    # P14 stamps the two equivalent fields in adjacent clock reads.
    return abs((left_dt - right_dt).total_seconds()) <= 1


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
