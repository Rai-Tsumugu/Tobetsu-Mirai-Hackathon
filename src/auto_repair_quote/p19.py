"""P19: validate and load a registered, human-approved quote preset."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any, Mapping, Sequence

from .common import QuoteError, number


def load_preset(
    presets: Sequence[Mapping[str, Any]], preset_id: str, as_of: str | None = None
) -> dict[str, Any]:
    """Return a validated copy of one preset, with stale prices flagged.

    This function never estimates vehicle condition or applies a blanket
    vehicle multiplier. Unknown required conditions remain unresolved for a
    human to confirm.
    """
    if not isinstance(preset_id, str) or not preset_id.strip():
        raise QuoteError("preset_id is required")
    if not isinstance(presets, Sequence) or isinstance(presets, (str, bytes)):
        raise QuoteError("presets must be a sequence")
    matches = [p for p in presets if isinstance(p, Mapping) and p.get("preset_id") == preset_id]
    if len(matches) != 1:
        raise QuoteError("preset_id must identify exactly one registered preset")

    preset = deepcopy(dict(matches[0]))
    for field in ("job_ref", "approved_by", "version", "inputs", "required_conditions", "default_quantity", "rate_ref", "item_refs"):
        if field not in preset:
            raise QuoteError(f"preset.{field} is required")
    number(preset["default_quantity"])
    _nonempty(preset["rate_ref"], "preset.rate_ref")
    _nonempty(preset["job_ref"], "preset.job_ref")
    _nonempty(preset["approved_by"], "preset.approved_by")
    if isinstance(preset["version"], bool) or not isinstance(preset["version"], int) or preset["version"] < 1:
        raise QuoteError("preset.version must be a positive integer")
    if "item_refs" in preset and (not isinstance(preset["item_refs"], list) or not preset["item_refs"]):
        raise QuoteError("preset.item_refs must be a non-empty list")
    if any(not isinstance(ref, str) or not ref.strip() for ref in preset["item_refs"]):
        raise QuoteError("preset.item_refs must contain nonempty IDs")
    if not isinstance(preset["required_conditions"], list):
        raise QuoteError("preset.required_conditions must be a list")

    inputs = preset["inputs"]
    if not isinstance(inputs, Mapping):
        raise QuoteError("preset.inputs must be an object")
    inputs = deepcopy(dict(inputs))
    if inputs.get("job_ref") != preset["job_ref"]:
        raise QuoteError("preset job_ref does not match registered inputs")
    rate = inputs.get("labor_rate")
    if not isinstance(rate, Mapping):
        raise QuoteError("preset inputs.labor_rate must be an object")
    if preset.get("rate_ref") is not None and rate.get("rate_ref") != preset["rate_ref"]:
        raise QuoteError("preset rate_ref does not match registered labor_rate")
    if "yen_per_person_hour" not in rate or not isinstance(rate.get("basis"), list) or not rate["basis"]:
        raise QuoteError("labor_rate requires yen_per_person_hour and basis evidence")
    number(rate["yen_per_person_hour"])
    if "effective_from" not in rate:
        raise QuoteError("labor_rate.effective_from is required")
    effective_from = _iso_date(rate["effective_from"], "labor_rate.effective_from")

    items = inputs.get("items")
    if not isinstance(items, list) or not items:
        raise QuoteError("preset inputs.items must be a non-empty list")
    item_by_id: dict[str, Mapping[str, Any]] = {}
    for item in items:
        if isinstance(item, dict) and "quantity_range" not in item:
            item["quantity_range"] = {band:preset["default_quantity"] for band in ("low","typical","high")}
            item["quantity_unit"] = item.get("unit")
    for item in items:
        if not isinstance(item, Mapping):
            raise QuoteError("preset items must be objects")
        item_id = item.get("item_id")
        _nonempty(item_id, "item.item_id")
        if item_id in item_by_id:
            raise QuoteError("preset item_id values must be unique")
        item_by_id[item_id] = item
        for field in ("name", "category", "unit", "unit_price", "price_type", "source", "updated_at"):
            if field not in item or item[field] is None:
                raise QuoteError(f"item.{field} is required")
        _iso_date(item["updated_at"], f"item {item_id}.updated_at")
        number(item["unit_price"])
        if not _has_text(item["source"]):
            raise QuoteError(f"item {item_id}.source is required")
        for field in ("name", "category", "unit"):
            if not _has_text(item[field]):
                raise QuoteError(f"item {item_id}.{field} is required")
        if item["price_type"] not in {"仕入", "販売"}:
            raise QuoteError(f"item {item_id}.price_type is invalid")
        if item["price_type"] == "仕入":
            markup = item.get("markup")
            if not isinstance(markup, Mapping) or not _has_text(markup.get("approved_by")):
                raise QuoteError(f"item {item_id} purchase markup requires approved_by")
    if "item_refs" in preset and (len(preset["item_refs"]) != len(set(preset["item_refs"])) or set(preset["item_refs"]) != set(item_by_id)):
        raise QuoteError("preset.item_refs do not match registered items")

    reference_date = _iso_date(as_of, "as_of") if as_of is not None else date.today()
    if reference_date < effective_from:
        raise QuoteError("preset labor rate is not yet effective as of requested date")

    warnings: list[str] = []
    refresh_required = False
    for item_id, item in item_by_id.items():
        if _iso_date(item["updated_at"], f"item {item_id}.updated_at") < reference_date:
            warnings.append(f"価格が更新日より古い可能性があります: {item_id} ({item['updated_at']})。人が更新を確認してください")
            refresh_required = True
    for condition in preset["required_conditions"]:
        if not _condition_resolved(condition):
            label = condition.get("label") or condition.get("condition") or "条件" if isinstance(condition, Mapping) else str(condition)
            warnings.append(f"未確認条件: {label}。人が確認してください")

    return {
        "preset_id": preset_id,
        "default_quantity": preset["default_quantity"],
        "rate_ref": preset["rate_ref"],
        "item_refs": deepcopy(preset["item_refs"]),
        "inputs": inputs,
        "warnings": warnings,
        "required_conditions": deepcopy(preset["required_conditions"]),
        "version": preset["version"],
        "refresh_required": refresh_required,
    }


def _iso_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise QuoteError(f"{field} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise QuoteError(f"{field} must be an ISO date") from None
    if parsed.isoformat() != value:
        raise QuoteError(f"{field} must be an ISO date")
    return parsed


def _nonempty(value: Any, field: str) -> None:
    if not _has_text(value):
        raise QuoteError(f"{field} is required")


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _condition_resolved(condition: Any) -> bool:
    return (
        isinstance(condition, Mapping)
        and condition.get("status") in {"satisfied", "confirmed", "resolved"}
        and condition.get("value") is not None
    )
