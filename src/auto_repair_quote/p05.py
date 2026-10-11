"""P05: apply one approved discount before tax."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any, Mapping

from .common import BANDS, QuoteError, make_line, number, range_value
from .p07 import apply as subtotal_apply
from .p09 import apply as tax_apply

_PREFIX = "discount:p05"


def apply(quote: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Return a copied quote with a validated, auditable discount row."""
    if not isinstance(quote, dict) or not isinstance(inputs, dict):
        raise QuoteError("quote and inputs must be objects")
    discount = inputs.get("discount")
    if discount is None:
        return deepcopy(quote)
    if not isinstance(discount, Mapping):
        raise QuoteError("discount must be an object")
    if discount.get("order") != "before_tax":
        raise QuoteError("only before_tax discounts are supported")
    if discount.get("scope") not in {"lines", "subtotal"}:
        raise QuoteError("discount.scope must be lines or subtotal")
    if discount.get("kind") not in {"amount", "rate"}:
        raise QuoteError("discount.kind must be amount or rate")
    if not _nonempty(discount.get("approved_by")) or not _nonempty(discount.get("reason")):
        raise QuoteError("discount requires approved_by and reason")

    lines = quote.get("lines")
    if not isinstance(lines, list) or any(not isinstance(line, dict) for line in lines):
        raise QuoteError("quote.lines must be a list of objects")
    line_ids = discount.get("line_ids")
    if not isinstance(line_ids, list) or any(not _nonempty(line_id) for line_id in line_ids):
        raise QuoteError("discount.line_ids must be a list of non-empty IDs")
    if len({str(item) for item in line_ids}) != len(line_ids):
        raise QuoteError("discount.line_ids must not contain duplicates")
    if discount["scope"] == "lines" and not line_ids:
        raise QuoteError("line discounts require at least one line_id")
    if discount["scope"] == "subtotal" and line_ids:
        raise QuoteError("subtotal discounts must use an empty line_ids list")

    # Remove the previous P05 row before computing the base, making reapply
    # idempotent and preventing its own adjustment from being discounted.
    base_lines = [line for line in lines if line.get("line_id") != _PREFIX]
    selected: list[dict[str, Any]] = []
    if discount["scope"] == "lines":
        by_id = {line.get("line_id"): line for line in base_lines}
        missing = [str(item) for item in line_ids if str(item) not in by_id]
        if missing:
            raise QuoteError(f"unknown discount line_id: {missing[0]}")
        selected = [by_id[str(item)] for item in line_ids]

    previous = next((line for line in lines if line.get("line_id") == _PREFIX), None)
    previous_amount = _negative_range(previous.get("amount")) if previous else {band: Decimal(0) for band in BANDS}
    base = _base_amount(discount["scope"], selected, quote, base_lines, previous_amount)
    value = _parse_discount_value(discount.get("value"), discount["kind"])
    amount = {}
    for band in BANDS:
        reduction = base[band] * value[band] if discount["kind"] == "rate" else value[band]
        if reduction < 0 or reduction > base[band]:
            raise QuoteError(f"discount exceeds eligible {band} amount")
        amount[band] = -reduction

    result = deepcopy(quote)
    result_lines = [line for line in result["lines"] if line.get("line_id") != _PREFIX]
    prior_reason = previous.get("reason") if previous else None
    source_ref = "subtotal" if discount["scope"] == "subtotal" else ",".join(map(str, line_ids))
    positive_amount = {band: -amount[band] for band in BANDS}
    line = make_line(
        line_id=_PREFIX,
        kind="discount",
        category=None,
        description="承認済み値引き",
        quantity_range={band: 1 for band in BANDS},
        unit="式",
        unit_price_range=positive_amount,
        amount=positive_amount,
        source_system="simulator",
        source_ref=source_ref,
        snapshot={
            "discount": deepcopy(dict(discount)),
            "scope": discount["scope"],
            "line_ids": [str(item) for item in line_ids],
            "eligible_amount": {band: _json(base[band]) for band in BANDS},
            "discount_amount": {band: _json(-amount[band]) for band in BANDS},
        },
        reason=f"{discount['reason']}（承認: {discount['approved_by']}）",
    )
    # Contract amount ranges permit reversed order specifically for negative
    # adjustments; common.money_range intentionally rejects negative values.
    line["amount"] = {band: _json(amount[band]) for band in BANDS}
    result_lines.append(line)
    result["lines"] = result_lines
    reasons = result.setdefault("reasons", [])
    if prior_reason and isinstance(reasons, list):
        result["reasons"] = [reason for reason in reasons if reason != prior_reason]
    result.setdefault("reasons", []).append(line["reason"])
    result = subtotal_apply(result)
    if "tax_policy" in inputs:
        return tax_apply(result, inputs)
    result["tax"] = {band: None for band in BANDS}
    result["total"] = {band: None for band in BANDS}
    result.pop("tax_snapshot", None)
    return result


def _base_amount(scope: str, selected: list[dict[str, Any]], quote: dict[str, Any],
                 base_lines: list[dict[str, Any]], previous_amount: dict[str, Decimal]) -> dict[str, Decimal]:
    if scope == "lines":
        totals = {band: Decimal(0) for band in BANDS}
        for line in selected:
            if line.get("kind") == "discount":
                raise QuoteError("discount lines cannot be targeted")
            values = _positive_range(line.get("amount"), "target line amount")
            for band in BANDS:
                totals[band] += values[band]
        return totals
    # Prefer the quote's authoritative subtotal. If it is absent, derive it
    # from positive non-discount line amounts.
    subtotal = quote.get("subtotal")
    if subtotal is not None:
        values = _positive_range(subtotal, "quote.subtotal")
        return {band: values[band] - previous_amount[band] for band in BANDS}
    totals = {band: Decimal(0) for band in BANDS}
    for line in base_lines:
        if line.get("kind") == "discount":
            continue
        values = _positive_range(line.get("amount"), "line amount")
        for band in BANDS:
            totals[band] += values[band]
    return totals


def _parse_discount_value(value: Any, kind: str) -> dict[str, Decimal]:
    raw = range_value(value) if isinstance(value, Mapping) else {band: number(value) for band in BANDS}
    parsed = {band: raw[band] for band in BANDS}
    if kind == "rate" and any(value > 1 for value in parsed.values()):
        raise QuoteError("discount rate must be between 0 and 1")
    return parsed


def _positive_range(value: Any, label: str) -> dict[str, Decimal]:
    if not isinstance(value, Mapping) or set(value) != set(BANDS):
        raise QuoteError(f"{label} must contain low, typical, and high")
    parsed: dict[str, Decimal] = {}
    for band in BANDS:
        raw = value[band]
        if raw is None or isinstance(raw, bool):
            raise QuoteError(f"{label} must be finite and non-negative")
        try:
            parsed[band] = Decimal(str(raw))
        except Exception:
            raise QuoteError(f"{label} must be finite and non-negative") from None
        if not parsed[band].is_finite() or parsed[band] < 0:
            raise QuoteError(f"{label} must be finite and non-negative")
    return parsed


def _negative_range(value: Any) -> dict[str, Decimal]:
    if not isinstance(value, Mapping) or set(value) != set(BANDS):
        raise QuoteError("existing P05 amount must contain low, typical, and high")
    parsed: dict[str, Decimal] = {}
    for band in BANDS:
        if value[band] is None or isinstance(value[band], bool):
            raise QuoteError("existing P05 amount must be finite and non-positive")
        try:
            parsed[band] = Decimal(str(value[band]))
        except Exception:
            raise QuoteError("existing P05 amount must be finite and non-positive") from None
        if not parsed[band].is_finite() or parsed[band] > 0:
            raise QuoteError("existing P05 amount must be finite and non-positive")
    return parsed


def _json(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _nonempty(value: Any) -> bool:
    return isinstance(value, (str, int)) and not isinstance(value, bool) and bool(str(value).strip())
