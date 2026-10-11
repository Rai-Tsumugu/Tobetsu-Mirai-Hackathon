"""P16: run a registered preset as a phone-time quote shortcut."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .common import QuoteError
from . import pipeline


def quick_quote(
    presets: Sequence[Mapping[str, Any]],
    preset_id: str,
    vehicle_ref: str | None = None,
) -> dict[str, Any]:
    """Calculate a fresh quote from a fictional preset without changing it.

    A shortcut is available only when the referenced job, rate, items, and
    vehicle are present and all required conditions are resolved. The quote
    still remains proposed; this function never confirms an amount.
    """
    if not isinstance(presets, Sequence) or isinstance(presets, (str, bytes)):
        raise QuoteError("presets must be a sequence")
    matches = [
        preset for preset in presets
        if isinstance(preset, Mapping) and preset.get("preset_id") == preset_id
    ]
    if len(matches) != 1:
        raise QuoteError("preset_id must identify exactly one registered preset")

    preset = deepcopy(dict(matches[0]))
    source_inputs = preset.get("inputs")
    if not isinstance(source_inputs, Mapping):
        raise QuoteError("preset.inputs must be a registered input bundle")
    inputs = deepcopy(dict(source_inputs))
    selected_vehicle = vehicle_ref if vehicle_ref is not None else inputs.get("vehicle_ref")
    checks = _registration_checks(preset, inputs, selected_vehicle)

    # Give every run its own identity and vary only the requested vehicle
    # reference in the registered input bundle.
    inputs["quote_id"] = str(uuid4())
    if selected_vehicle is not None:
        inputs["vehicle_ref"] = selected_vehicle

    required_conditions = preset.get("required_conditions", [])
    unresolved = _unresolved_conditions(required_conditions)
    if unresolved:
        labor = inputs.get("labor")
        if isinstance(labor, dict):
            existing_unknowns = labor.get("unknowns")
            if not isinstance(existing_unknowns, list):
                existing_unknowns = []
            labor["unknowns"] = [*existing_unknowns, *unresolved]

    quote = pipeline.calculate(inputs)
    quote.setdefault("reasons", []).append(
        "Simulatorの登録価格スナップショットを使った架空デモ。現在価格・実相場ではありません。"
    )
    shortcut_available = all(checks.values()) and not unresolved and quote.get("status") != "blocked"
    if not shortcut_available:
        quote["status"] = "blocked"
        quote["selected_band"] = None
        quote["issues"] = quote.get("issues", []) + [{"code":"shortcut_unavailable", "path":"preset", "message":"登録・出所・今回条件を確認してください"}]
        for field in ("subtotal", "tax", "total"):
            quote[field] = {band: None for band in ("low", "typical", "high")}
    return {
        "inputs": inputs,
        "quote": quote,
        "tap_count": 3,
        "shortcut_available": shortcut_available,
        "registration_checks": checks,
        "fictional": quote.get("fictional", False),
    }


def _registration_checks(
    preset: Mapping[str, Any], inputs: Mapping[str, Any], vehicle_ref: Any
) -> dict[str, bool]:
    """Check that every shortcut dependency is backed by this preset bundle."""
    job_ref = preset.get("job_ref") or preset.get("job_id")
    job_registered = (
        _nonempty(job_ref)
        and inputs.get("job_ref") == job_ref
        and _nonempty(preset.get("name"))
    )

    rate = inputs.get("labor_rate")
    rate_registered = (
        isinstance(rate, Mapping)
        and _nonempty(rate.get("yen_per_person_hour"))
        and _nonempty(rate.get("effective_from"))
        and isinstance(rate.get("basis"), list)
        and bool(rate.get("basis"))
    )
    rate_ref = preset.get("rate_ref")
    if rate_ref is not None:
        rate_registered = rate_registered and rate.get("rate_ref") == rate_ref

    items = inputs.get("items")
    item_ids = {
        item.get("item_id") for item in items
        if isinstance(item, Mapping) and _nonempty(item.get("item_id"))
    } if isinstance(items, list) else set()
    expected_item_refs = preset.get("item_refs")
    items_registered = isinstance(items, list) and len(items) > 0 and len(item_ids) == len(items)
    if expected_item_refs is not None:
        items_registered = (
            items_registered
            and isinstance(expected_item_refs, list)
            and set(expected_item_refs) == item_ids
        )
    if items_registered:
        for item in items:
            if item.get("price_type") == "仕入":
                markup = item.get("markup")
                if not isinstance(markup, Mapping) or not _nonempty(markup.get("approved_by")) or not _nonempty(markup.get("reason")):
                    items_registered = False
                    break
            elif item.get("price_type") != "販売":
                items_registered = False
                break
            if not _simulator(item.get("source")):
                items_registered = False
                break

    vehicle_registered = _nonempty(vehicle_ref)
    registered_vehicles = preset.get("vehicle_refs")
    if registered_vehicles is None:
        registered_vehicles = [inputs.get("vehicle_ref")]
    vehicle_registered = (
        vehicle_registered
        and isinstance(registered_vehicles, list)
        and vehicle_ref in registered_vehicles
    )
    return {
        "job_registered": bool(job_registered),
        "rate_registered": bool(rate_registered),
        "items_registered": bool(items_registered),
        "vehicle_registered": bool(vehicle_registered),
        "simulator_only": all(
            _simulator(item.get("source"))
            for item in inputs.get("items", [])
            if isinstance(item, Mapping)
        ),
    }


def _unresolved_conditions(conditions: Any) -> list[str]:
    if conditions in (None, []):
        return []
    if not isinstance(conditions, list):
        return ["required_conditionsの形式が不明"]
    unresolved = []
    for condition in conditions:
        if isinstance(condition, Mapping):
            if condition.get("status") in {"satisfied", "confirmed", "resolved"} and condition.get("value") is not None:
                continue
            label = condition.get("label") or condition.get("condition") or "条件"
            unresolved.append(f"未確認条件: {label}")
        elif isinstance(condition, str) and condition.strip():
            unresolved.append(f"未確認条件: {condition.strip()}")
        else:
            unresolved.append("required_conditionsに不明な値")
    return unresolved


def _simulator(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() in {"simulator", "架空", "fictional"}


def _nonempty(value: Any) -> bool:
    return value is not None and not isinstance(value, bool) and bool(str(value).strip())
