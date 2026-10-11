"""P24: compare stored purchase and sales price history by item."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any, Iterable, Mapping

from .common import QuoteError
from .p04 import selling_price


def price_comparison(history: Iterable[Mapping[str, Any]], item_id: str) -> dict[str, Any]:
    """Return dated price records without comparing prices across units.

    Approved purchase markup is shown as a proposal. A missing or invalid
    approval leaves the proposal unknown; it is never replaced with zero.
    """
    if not isinstance(item_id, str) or not item_id.strip():
        raise QuoteError("item_id is required")
    try:
        rows = list(history)
    except TypeError:
        raise QuoteError("history must be iterable") from None

    prices: list[dict[str, Any]] = []
    units: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise QuoteError(f"history.{index} must be an object")
        if str(raw.get("item_id", "")) != item_id:
            continue
        price_type = raw.get("price_type")
        unit = raw.get("unit")
        if price_type not in {"仕入", "販売"}:
            raise QuoteError(f"history.{index}.price_type must be 仕入 or 販売")
        if not isinstance(unit, str) or not unit.strip():
            raise QuoteError(f"history.{index}.unit is required")
        for field in ("source", "updated_at"):
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                raise QuoteError(f"history.{index}.{field} is required")
        _validate_date(raw["updated_at"], index)

        proposal = None
        confirmation_status = "未確認"
        try:
            proposal = selling_price(raw)
        except QuoteError:
            # Preserve the observed purchase price while withholding an
            # unapproved calculated selling price.
            if price_type == "販売":
                raise
        else:
            confirmation_status = "確認済み" if price_type == "販売" else "承認済み掛率"

        prices.append({
            "price_type": price_type,
            "unit": unit,
            "unit_price": deepcopy(raw.get("unit_price")),
            "source": raw["source"],
            "updated_at": raw["updated_at"],
            "selling_price_proposal": deepcopy(proposal),
            "confirmation_status": confirmation_status,
        })
        units.add("".join(unit.split()))

    if len(units) > 1:
        raise QuoteError("unit mismatch: do not compare prices across different units")
    return {"item_id": item_id, "prices": prices, "unit_mismatch": False}


def save_price_history(store: Any, item: Mapping[str, Any]) -> None:
    """Validate a price record with P04, then persist an immutable copy."""
    if not isinstance(item, Mapping):
        raise QuoteError("item must be an object")
    # P04 validates price type, numeric value, and approval when applicable.
    try:
        selling_price(item)
    except QuoteError:
        # Unapproved purchase prices are valid historical facts; only their
        # selling-price proposal is unavailable. Other malformed data fails.
        if item.get("price_type") != "仕入":
            raise
        from .common import money_range
        money_range(item.get("unit_price"))
    for field in ("item_id", "unit", "source", "updated_at"):
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise QuoteError(f"{field} is required")
    _validate_date(item["updated_at"], 0)
    store.save_price(deepcopy(dict(item)))


def compare_item_prices(store: Any, item_id: str) -> dict[str, Any]:
    """Load an item's persisted history and build its comparison view."""
    if not isinstance(item_id, str) or not item_id.strip():
        raise QuoteError("item_id is required")
    return price_comparison(store.list_prices(item_id), item_id)


def _validate_date(value: str, index: int) -> None:
    try:
        date.fromisoformat(value)
    except ValueError:
        raise QuoteError(f"history.{index}.updated_at must be an ISO date") from None
