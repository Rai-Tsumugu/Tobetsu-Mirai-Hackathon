"""P09: calculate quote tax independently for each estimate band."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any, Mapping

from .common import BANDS, QuoteError, _json_number
from .p07 import apply as subtotal_apply

_ROUNDING = {
    "floor": ROUND_FLOOR,
    "half_up": ROUND_HALF_UP,
    "ceil": ROUND_CEILING,
}


def apply(quote: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Return a copied quote with its configured tax snapshot and totals."""
    if not isinstance(quote, dict):
        raise QuoteError("quote must be an object")
    if not isinstance(inputs, dict):
        raise QuoteError("inputs must be an object")
    policy = inputs.get("tax_policy")
    if not isinstance(policy, Mapping):
        raise QuoteError("inputs.tax_policy must be an object")
    allowed = {"rate", "rounding", "source", "approved_by", "effective_date", "taxable_line_ids"}
    if set(policy) - allowed:
        raise QuoteError("tax_policy contains unknown settings")
    if not {"rate", "rounding", "source"}.issubset(policy):
        raise QuoteError("tax_policy requires rate, rounding, and source")

    rate = _rate(policy["rate"])
    rounding = policy["rounding"]
    if rounding not in _ROUNDING:
        raise QuoteError("tax_policy.rounding is unknown")
    source = policy["source"]
    if source not in {"simulator", "factory"}:
        raise QuoteError("tax_policy.source is unknown")
    approved_by = policy.get("approved_by")
    effective_date = policy.get("effective_date")
    if source == "factory" and (not _nonempty_string(approved_by) or not _nonempty_string(effective_date)):
        raise QuoteError("factory tax policy requires approved_by and effective_date")

    lines = quote.get("lines")
    if not isinstance(lines, list):
        raise QuoteError("quote.lines must be a list")
    line_ids: list[str] = []
    line_by_id: dict[str, Mapping[str, Any]] = {}
    for index, line in enumerate(lines):
        if not isinstance(line, Mapping):
            raise QuoteError(f"quote.lines.{index} must be an object")
        line_id = line.get("line_id")
        if not isinstance(line_id, (str, int)) or isinstance(line_id, bool) or not str(line_id).strip():
            raise QuoteError(f"quote.lines.{index}.line_id is required")
        key = str(line_id)
        if key in line_by_id:
            raise QuoteError(f"duplicate line_id: {key}")
        line_ids.append(key)
        line_by_id[key] = line

    if source == "factory" and "taxable_line_ids" not in policy:
        raise QuoteError("factory tax policy requires explicit taxable_line_ids")
    taxable = policy.get("taxable_line_ids", line_ids)
    if not isinstance(taxable, list):
        raise QuoteError("tax_policy.taxable_line_ids must be a list")
    taxable_ids: list[str] = []
    for item in taxable:
        if not isinstance(item, (str, int)) or isinstance(item, bool) or not str(item).strip():
            raise QuoteError("tax_policy.taxable_line_ids contains an invalid id")
        key = str(item)
        if key not in line_by_id:
            raise QuoteError(f"unknown taxable line id: {key}")
        if key in taxable_ids:
            raise QuoteError(f"duplicate taxable line id: {key}")
        taxable_ids.append(key)

    # A tax-before discount follows its target lines' tax treatment. Mixed
    # taxable/non-taxable bundles require an explicit split instead of guessing.
    if "taxable_line_ids" in policy:
        taxable_set = set(taxable_ids)
        for key, line in line_by_id.items():
            if line.get("kind") != "discount":
                continue
            snapshot = line.get("snapshot", {})
            target_ids = snapshot.get("line_ids", [])
            if snapshot.get("scope") == "subtotal":
                target_ids = [ref for ref, target in line_by_id.items() if target.get("kind") != "discount"]
            if not target_ids:
                raise QuoteError("discount tax treatment requires target lines")
            overlap = set(target_ids) & taxable_set
            if overlap and overlap != set(target_ids):
                raise QuoteError("mixed-tax discount requires separate approved target lines")
            if overlap and key not in taxable_set:
                taxable_ids.append(key)
                taxable_set.add(key)
            if not overlap and key in taxable_set:
                raise QuoteError("non-taxable discount cannot be marked taxable")
    calculated = subtotal_apply(quote)
    taxable_subtotal = {band: Decimal(0) for band in BANDS}
    for line_id in taxable_ids:
        amount = line_by_id[line_id].get("amount")
        values = _signed_range(amount, line_id)
        for band in BANDS:
            taxable_subtotal[band] += values[band]

    taxes: dict[str, Decimal] = {}
    for band in BANDS:
        raw_tax = taxable_subtotal[band] * rate
        taxes[band] = raw_tax.quantize(Decimal("1"), rounding=_ROUNDING[rounding])
    totals = {
        band: Decimal(str(calculated["subtotal"][band])) + taxes[band]
        for band in BANDS
    }

    result = deepcopy(calculated)
    result["tax"] = {band: _json_number(taxes[band]) for band in BANDS}
    result["total"] = {band: _json_number(totals[band]) for band in BANDS}
    result["tax_snapshot"] = {
        "rate": _json_number(rate),
        "rounding": rounding,
        "taxable_line_ids": deepcopy(taxable_ids),
        "effective_date": effective_date,
        "source": source,
    }
    if approved_by is not None:
        result["tax_snapshot"]["approved_by"] = approved_by
    return result


def tax_summary(quote: Mapping[str, Any]) -> dict[str, dict[str, int | float]]:
    """Return the stored subtotal, tax, and total ranges by estimate band."""
    if not isinstance(quote, Mapping):
        raise QuoteError("quote must be an object")
    snapshot = quote.get("tax_snapshot")
    if not isinstance(snapshot, Mapping):
        raise QuoteError("quote.tax_snapshot is required")
    subtotal = subtotal_apply(dict(quote))["subtotal"]
    tax = quote.get("tax")
    total = quote.get("total")
    return {
        band: {
            "subtotal": subtotal[band],
            "tax": _range_value(tax, band, "tax"),
            "total": _range_value(total, band, "total"),
        }
        for band in BANDS
    }


def _rate(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise QuoteError("tax_policy.rate must be between 0 and 1")
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise QuoteError("tax_policy.rate must be between 0 and 1") from None
    if not rate.is_finite() or not Decimal(0) <= rate <= Decimal(1):
        raise QuoteError("tax_policy.rate must be between 0 and 1")
    return rate


def _signed_range(value: Any, line_id: str) -> dict[str, Decimal]:
    if isinstance(value, Mapping):
        if set(value) != set(BANDS):
            raise QuoteError(f"line {line_id} amount must contain low, typical, and high")
        raw = value
    elif value is not None:
        raw = {band: value for band in BANDS}
    else:
        raise QuoteError(f"line {line_id} amount must be finite")
    parsed: dict[str, Decimal] = {}
    for band in BANDS:
        value = raw[band]
        if value is None or isinstance(value, bool):
            raise QuoteError(f"line {line_id} amount.{band} must be finite")
        try:
            parsed[band] = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise QuoteError(f"line {line_id} amount.{band} must be finite") from None
        if not parsed[band].is_finite():
            raise QuoteError(f"line {line_id} amount.{band} must be finite")
    return parsed


def _range_value(value: Any, band: str, label: str) -> int | float:
    if not isinstance(value, Mapping) or set(value) != set(BANDS):
        raise QuoteError(f"quote.{label} must contain low, typical, and high")
    raw = value[band]
    if raw is None or isinstance(raw, bool):
        raise QuoteError(f"quote.{label}.{band} must be finite")
    try:
        parsed = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        raise QuoteError(f"quote.{label}.{band} must be finite") from None
    if not parsed.is_finite():
        raise QuoteError(f"quote.{label}.{band} must be finite")
    return _json_number(parsed)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
