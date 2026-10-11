"""P17: persist an in-progress quote and resume it with an explicit price choice."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from .common import QuoteError


_ITEM_WORK_FIELDS = {"item_id", "quantity_range", "quantity_unit", "unit"}


def save_draft(store: Any, draft_id: str, inputs: Mapping[str, Any], step: int = 0) -> dict[str, Any]:
    """Save an isolated input and price snapshot for later continuation."""
    if not isinstance(draft_id, str) or not draft_id.strip():
        raise QuoteError("draft_id is required")
    if not isinstance(inputs, Mapping):
        raise QuoteError("inputs must be an object")
    if isinstance(step, bool) or not isinstance(step, int) or step < 0:
        raise QuoteError("step must be a non-negative integer")

    saved_inputs = deepcopy(dict(inputs))
    paused_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    draft = {
        "draft_id": draft_id,
        "inputs": saved_inputs,
        "input_refs": {
            key: deepcopy(saved_inputs[key])
            for key in ("job_ref", "customer_ref", "vehicle_ref")
            if key in saved_inputs
        },
        "step": step,
        "price_snapshots": _price_snapshot(saved_inputs),
        "paused_at": paused_at,
        "resume_mode": None,
    }
    return store.save_draft(draft)


def resume_draft(
    store: Any,
    draft_id: str,
    resume_mode: str,
    current_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resume saved work using current prices or the explicitly retained snapshot."""
    if resume_mode not in {"current", "snapshot"}:
        raise QuoteError("resume_mode must be explicitly current or snapshot")
    draft = store.get_draft(draft_id)
    saved_inputs = draft.get("inputs")
    if not isinstance(saved_inputs, Mapping):
        raise QuoteError("saved draft inputs are invalid")
    resumed = deepcopy(dict(saved_inputs))

    if resume_mode == "current":
        if not isinstance(current_inputs, Mapping):
            raise QuoteError("current_inputs are required for current price mode")
        _update_current_prices(resumed, current_inputs)
        notice = "現在価格に更新しました。"
    else:
        paused_at = draft.get("paused_at")
        if not paused_at:
            raise QuoteError("saved price snapshot date is missing")
        notice = f"当時価格のまま再開しています（保存日: {paused_at}）。"

    draft["resume_mode"] = resume_mode
    store.save_draft(draft)
    return {
        "draft_id": draft_id,
        "inputs": resumed,
        "step": draft.get("step", 0),
        "resume_mode": resume_mode,
        "price_notice": notice,
    }


def list_drafts(store: Any) -> list[dict[str, Any]]:
    """Return persisted drafts as independent values."""
    return deepcopy(store.list_drafts())


def _update_current_prices(saved: dict[str, Any], current: Mapping[str, Any]) -> None:
    current_rate = current.get("labor_rate")
    current_items = current.get("items")
    saved_items = saved.get("items")
    if not isinstance(current_rate, Mapping):
        raise QuoteError("current labor_rate is unavailable")
    if not isinstance(saved_items, list) or not isinstance(current_items, list):
        raise QuoteError("current item prices are unavailable")

    saved_by_id = _items_by_id(saved_items, "saved")
    current_by_id = _items_by_id(current_items, "current")
    if set(saved_by_id) != set(current_by_id):
        missing = sorted(set(saved_by_id) - set(current_by_id))
        extra = sorted(set(current_by_id) - set(saved_by_id))
        raise QuoteError(f"current item price mapping mismatch (missing={missing}, extra={extra})")

    saved["labor_rate"] = deepcopy(dict(current_rate))
    for item_id, old_item in saved_by_id.items():
        new_item = current_by_id[item_id]
        if new_item.get("unit") != old_item.get("unit"):
            raise QuoteError(f"current unit mismatch for item_id: {item_id}")
        if "unit_price" not in new_item or new_item["unit_price"] is None:
            raise QuoteError(f"current price is unavailable for item_id: {item_id}")
        for field, value in new_item.items():
            if field not in _ITEM_WORK_FIELDS:
                old_item[field] = deepcopy(value)


def _items_by_id(items: list[Any], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise QuoteError(f"{label} items must be objects")
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or not item_id.strip() or item_id in result:
            raise QuoteError(f"{label} items require unique item_id values")
        result[item_id] = item if isinstance(item, dict) else dict(item)
    return result


def _price_snapshot(inputs: Mapping[str, Any]) -> dict[str, Any]:
    items = inputs.get("items", [])
    return {
        "labor_rate": deepcopy(inputs.get("labor_rate")),
        "items": [
            {
                key: deepcopy(value)
                for key, value in item.items()
                if key not in _ITEM_WORK_FIELDS
            }
            for item in items
            if isinstance(item, Mapping)
        ] if isinstance(items, list) else [],
    }
