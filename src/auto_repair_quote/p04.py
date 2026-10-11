"""P04: apply an approved purchase markup once and snapshot item prices."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any, Mapping

from .common import BANDS, QuoteError, make_line, money_range, multiply_ranges, number, range_value

_CATEGORIES = {"部品", "塗料", "溶剤", "消耗品"}
_PRICE_TYPES = {"仕入", "販売"}
_LINE_PREFIX = "item-price:"


def selling_price(item: Mapping[str, Any]) -> dict[str, int | float]:
    """Return a validated final unit-price range for an item.

    A supplied sales price is already the selling price. Purchase prices need
    a multiplier with an approver and reason, and that multiplier is applied
    exactly once. ``unit_price`` and ``markup.value`` may each be scalar or a
    low/typical/high range; ranges are paired by matching band.
    """
    if not isinstance(item, Mapping):
        raise QuoteError("item must be an object")
    price_type = item.get("price_type")
    if price_type not in _PRICE_TYPES:
        raise QuoteError("price_type must be 仕入 or 販売")
    base = _finite_range(money_range(item.get("unit_price")))
    if price_type == "販売":
        return base

    markup = item.get("markup")
    if not isinstance(markup, Mapping):
        raise QuoteError("purchase price requires an approved markup")
    if not _nonempty(markup.get("approved_by")) or not _nonempty(markup.get("reason")):
        raise QuoteError("purchase markup requires approved_by and reason")
    factor = _finite_range(money_range(markup.get("value")))
    return _finite_range(multiply_ranges(base, factor))


def apply(quote: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Add or replace item quote rows by item_id, preserving the inputs."""
    if not isinstance(quote, dict) or not isinstance(inputs, dict):
        raise QuoteError("quote and inputs must be objects")
    items = inputs.get("items")
    if not isinstance(items, list):
        raise QuoteError("items must be a list")

    prepared: list[tuple[dict[str, Any], dict[str, int | float]]] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise QuoteError(f"items.{index} must be an object")
        item_id = item.get("item_id")
        if not _nonempty(item_id):
            raise QuoteError(f"items.{index}.item_id is required")
        item_id = str(item_id)
        if item_id in seen:
            raise QuoteError(f"duplicate item_id: {item_id}")
        seen.add(item_id)
        category = item.get("category")
        if category not in _CATEGORIES:
            raise QuoteError(f"items.{index}.category is invalid")
        if item.get("price_type") not in _PRICE_TYPES:
            raise QuoteError(f"items.{index}.price_type is invalid")
        unit = item.get("unit")
        quantity_unit = item.get("quantity_unit")
        if not _nonempty(unit) or not _nonempty(quantity_unit) or _unit_key(unit) != _unit_key(quantity_unit):
            raise QuoteError(f"items.{index}.quantity_unit must match unit")
        quantity = range_value(item.get("quantity_range"))
        final_price = selling_price(item)
        # Confirm amount arithmetic with finite, non-negative values.
        amount = multiply_ranges(quantity, final_price)
        for field in ("source", "updated_at"):
            if not _nonempty(item.get(field)):
                raise QuoteError(f"items.{index}.{field} is required")
        _validate_date(item["updated_at"], index)
        prepared.append((item, amount))

    result = deepcopy(quote)
    lines = result.setdefault("lines", [])
    if not isinstance(lines, list):
        raise QuoteError("quote.lines must be a list")
    item_ids = {str(item["item_id"]) for item, _ in prepared}
    # Replace earlier P04 rows for the same items; leave all other lines alone.
    lines[:] = [
        line for line in lines
        if not (isinstance(line, dict) and line.get("line_id") == _line_id(line.get("source_ref"))
                and str(line.get("source_ref")) in item_ids)
    ]

    for item, amount in prepared:
        item_id = str(item["item_id"])
        base_price = money_range(item["unit_price"])
        markup_snapshot = deepcopy(item.get("markup")) if item.get("price_type") == "仕入" else None
        final_price = selling_price(item)
        snapshot = {
            "item_id": item_id,
            "price_type": item["price_type"],
            "base_price": base_price,
            "final_unit_price": final_price,
            "markup": markup_snapshot,
            "source": item["source"],
            "updated_at": item["updated_at"],
        }
        category = item["category"]
        line = make_line(
            line_id=_line_id(item_id),
            kind="parts" if category == "部品" else "materials",
            category=category,
            description=str(item.get("name") or item_id),
            quantity_range=item["quantity_range"],
            unit=str(item["unit"]).strip(),
            unit_price_range=final_price,
            amount=amount,
            source_system=str(item["source"]),
            source_ref=item_id,
            snapshot=snapshot,
            reason=_reason(item),
        )
        lines.append(line)
    return result


def _line_id(item_id: Any) -> str:
    return f"{_LINE_PREFIX}{item_id}"


def _finite_range(value: Mapping[str, Any]) -> dict[str, int | float]:
    """Reject float overflow introduced while converting Decimal to JSON numbers."""
    parsed = {band: value[band] for band in BANDS}
    for band in BANDS:
        number(parsed[band])
    return parsed


def _reason(item: Mapping[str, Any]) -> str:
    if item.get("price_type") == "販売":
        return "登録済み販売単価 × 同一帯の数量（掛率なし）"
    markup = item["markup"]
    return f"仕入単価 × 承認済み掛率 {markup['value']}（{markup['approved_by']}: {markup['reason']}）"


def _unit_key(value: Any) -> str:
    return "".join(value.split()) if isinstance(value, str) else ""


def _nonempty(value: Any) -> bool:
    return isinstance(value, (str, int)) and not isinstance(value, bool) and bool(str(value).strip())


def _validate_date(value: Any, index: int) -> None:
    if not isinstance(value, str):
        raise QuoteError(f"items.{index}.updated_at must be an ISO date")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise QuoteError(f"items.{index}.updated_at must be an ISO date") from None
