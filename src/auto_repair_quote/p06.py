"""P06: apply an approved minimum labor charge or subtotal floor."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .common import BANDS, QuoteError

_LINE_ID = "minimum-rule-adjustment"


def apply(quote: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Return a copied quote with a recalculated minimum adjustment row.

    ``scope`` is either labor (labor rows only) or subtotal (all pre-tax rows,
    including negative discounts). Existing P06 rows are removed before the
    base is recalculated, making repeated application deterministic.
    """
    if not isinstance(quote, dict) or not isinstance(inputs, dict):
        raise QuoteError("quote and inputs must be objects")
    rule = inputs.get("minimum_rule")
    if rule is None:
        return deepcopy(quote)
    parsed_rule = _validate_rule(rule)

    result = deepcopy(quote)
    lines = result.get("lines")
    if not isinstance(lines, list):
        raise QuoteError("quote.lines must be a list")
    lines[:] = [line for line in lines if not _is_p06_line(line)]

    current = {band: Decimal(0) for band in BANDS}
    for index, line in enumerate(lines):
        if not isinstance(line, Mapping):
            raise QuoteError(f"quote.lines.{index} must be an object")
        kind = line.get("kind")
        amount = line.get("amount")
        values = _amount_by_band(amount, index, allow_negative=(kind == "discount"))
        if parsed_rule["scope"] == "labor" and kind != "labor":
            continue
        for band in BANDS:
            current[band] += values[band]

    approved = bool(parsed_rule["approved_by"])
    adjustment = {
        band: max(Decimal(0), parsed_rule["amount"] - current[band]) if approved else Decimal(0)
        for band in BANDS
    }
    adjustment_json = {band: _json_number(adjustment[band]) for band in BANDS}
    reason = (
            f"{parsed_rule['scope']} minimum { _json_number(parsed_rule['amount']) }; "
            "adjustment=max(0, minimum-current) by band"
            if approved else "未承認の最低額ルール案。金額は加算していません。"
        )
    row = {
        "line_id": _LINE_ID,
        "kind": "adjustment",
        "category": parsed_rule["scope"],
        "description": "最低工賃調整" if parsed_rule["scope"] == "labor" else "最低小計調整",
        "quantity_range": {band: 1 for band in BANDS},
        "unit": "式",
        "unit_price_range": deepcopy(adjustment_json),
        "amount": adjustment_json,
        "source_system": "minimum_rule",
        "source_ref": parsed_rule["effective_from"],
        "snapshot": {"minimum_rule": deepcopy(rule), "scope": parsed_rule["scope"]},
        "reason": reason,
        "status": "calculated" if approved else "proposed",
    }
    lines.append(row)
    if not approved:
        result.setdefault("reasons", []).append("最低額ルールは未承認のため、金額に反映していません。")
    return result


def _validate_rule(rule: Any) -> dict[str, Any]:
    if not isinstance(rule, Mapping):
        raise QuoteError("minimum_rule must be an object")
    scope = rule.get("scope")
    if scope not in ("labor", "subtotal"):
        raise QuoteError("minimum_rule.scope must be labor or subtotal")
    amount = _decimal(rule.get("amount"), "minimum_rule.amount")
    effective_from = rule.get("effective_from")
    if not isinstance(effective_from, str):
        raise QuoteError("minimum_rule.effective_from must be an ISO date")
    try:
        date.fromisoformat(effective_from)
    except ValueError:
        raise QuoteError("minimum_rule.effective_from must be an ISO date") from None
    reason = rule.get("reason")
    if not _nonempty(reason):
        raise QuoteError("minimum_rule.reason is required")
    approved_by = rule.get("approved_by")
    return {
        "scope": scope,
        "amount": amount,
        "effective_from": effective_from,
        "approved_by": str(approved_by).strip() if _nonempty(approved_by) else None,
        "reason": reason.strip(),
    }


def _amount_by_band(value: Any, index: int, *, allow_negative: bool) -> dict[str, Decimal]:
    if isinstance(value, Mapping):
        if set(value) != set(BANDS):
            raise QuoteError(f"quote.lines.{index}.amount must contain low, typical, and high")
        raw = value
    else:
        raw = {band: value for band in BANDS}
    parsed = {band: _decimal(raw[band], f"quote.lines.{index}.amount.{band}", allow_negative=allow_negative)
              for band in BANDS}
    if not parsed["low"] <= parsed["typical"] <= parsed["high"]:
        raise QuoteError(f"quote.lines.{index}.amount bands must be ordered")
    return parsed


def _decimal(value: Any, label: str, *, allow_negative: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise QuoteError(f"{label} must be finite and non-negative")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise QuoteError(f"{label} must be finite and non-negative") from None
    if not parsed.is_finite() or (parsed < 0 and not allow_negative):
        raise QuoteError(f"{label} must be finite and non-negative")
    return parsed


def _json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    result = float(value)
    if not Decimal(str(result)).is_finite():
        raise QuoteError("result must be finite")
    return result


def _is_p06_line(line: Any) -> bool:
    return isinstance(line, Mapping) and line.get("line_id") == _LINE_ID


def _nonempty(value: Any) -> bool:
    return isinstance(value, (str, int)) and not isinstance(value, bool) and bool(str(value).strip())
