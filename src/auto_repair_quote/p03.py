"""P03: validate units and stop quotes whose amounts are ambiguous."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .common import BANDS, QuoteError, range_value

_ITEM_CATEGORIES = {"部品", "塗料", "溶剤", "消耗品"}
_PRICE_TYPES = {"仕入", "販売"}


def _unit_key(value: Any) -> str | None:
    """Normalize whitespace only; unit conversion and aliases are forbidden."""
    if not isinstance(value, str) or not value.strip():
        return None
    return "".join(value.split())


def validate_inputs(inputs: Any) -> list[dict[str, str]]:
    """Return structured validation issues without mutating the supplied data."""
    issues: list[dict[str, str]] = []

    def add(code: str, path: str, message: str) -> None:
        issues.append({"code": code, "path": path, "message": message})

    if not isinstance(inputs, dict):
        return [{"code": "invalid_inputs", "path": "", "message": "inputs must be an object"}]

    labor = inputs.get("labor")
    if not isinstance(labor, dict):
        add("missing_labor", "labor", "labor must be an object")
    else:
        hours = labor.get("person_hours")
        if not isinstance(hours, dict) or any(k not in hours for k in BANDS):
            add("invalid_person_hours", "labor.person_hours", "low, typical, and high person-hours are required")
        else:
            parsed: dict[str, float] = {}
            for band in BANDS:
                value = hours[band]
                if value is None or isinstance(value, bool):
                    add("invalid_person_hours", f"labor.person_hours.{band}", "value must be finite and non-negative")
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError, OverflowError):
                    add("invalid_person_hours", f"labor.person_hours.{band}", "value must be finite and non-negative")
                    continue
                if not __import__("math").isfinite(number) or number < 0:
                    add("invalid_person_hours", f"labor.person_hours.{band}", "value must be finite and non-negative")
                else:
                    parsed[band] = number
            if len(parsed) == len(BANDS) and not parsed["low"] <= parsed["typical"] <= parsed["high"]:
                add("unordered_person_hours", "labor.person_hours", "must satisfy low <= typical <= high")
        unknowns = labor.get("unknowns", [])
        if not isinstance(unknowns, list):
            add("invalid_unknowns", "labor.unknowns", "unknowns must be a list")
        elif unknowns:
            add("unresolved_unknowns", "labor.unknowns", "unresolved labor unknowns block quote amounts")

    rate = inputs.get("labor_rate")
    if not isinstance(rate, dict):
        add("missing_labor_rate", "labor_rate", "labor_rate must be an object")
    else:
        basis = rate.get("basis")
        if not isinstance(basis, list) or not basis:
            add("missing_rate_basis", "labor_rate.basis", "rate basis and its evidence are required")
        else:
            has_evidence = False
            for index, entry in enumerate(basis):
                path = f"labor_rate.basis.{index}"
                if not isinstance(entry, dict):
                    add("invalid_rate_basis", path, "basis entry must be an object")
                    continue
                unit = _unit_key(entry.get("unit"))
                if unit != "円/人時":
                    add("invalid_rate_unit", f"{path}.unit", "unit must be 円/人時")
                if entry.get("label") not in (None, "") and entry.get("value") is not None:
                    has_evidence = True
            if not has_evidence:
                add("missing_rate_evidence", "labor_rate.basis", "at least one basis entry needs label and value")
        if rate.get("effective_from") in (None, ""):
            add("missing_effective_from", "labor_rate.effective_from", "effective_from is required")

    items = inputs.get("items")
    if not isinstance(items, list):
        add("invalid_items", "items", "items must be a list")
    else:
        for index, item in enumerate(items):
            path = f"items.{index}"
            if not isinstance(item, dict):
                add("invalid_item", path, "item must be an object")
                continue
            if item.get("category") not in _ITEM_CATEGORIES:
                add("invalid_category", f"{path}.category", "category must be 部品, 塗料, 溶剤, or 消耗品")
            if item.get("price_type") not in _PRICE_TYPES:
                add("invalid_price_type", f"{path}.price_type", "price_type must be 仕入 or 販売")
            item_unit = _unit_key(item.get("unit"))
            if item_unit is None:
                add("missing_item_unit", f"{path}.unit", "item unit is required")
            quantity_unit = _unit_key(item.get("quantity_unit"))
            if quantity_unit is None or item_unit is None or quantity_unit != item_unit:
                add("unit_mismatch", f"{path}.quantity_unit", "quantity_unit must match item.unit")
            quantity = item.get("quantity_range")
            try:
                range_value(quantity)
            except QuoteError as error:
                add("invalid_quantity_range", f"{path}.quantity_range", str(error))
            for field in ("source", "updated_at"):
                if item.get(field) in (None, ""):
                    add(f"missing_{field}", f"{path}.{field}", f"{field} is required")
    return issues


def apply(quote: dict, inputs: dict) -> dict:
    """Return a copied quote marked blocked when unit/input checks fail."""
    if not isinstance(quote, dict):
        raise ValueError("quote must be an object")
    result = deepcopy(quote)
    issues = validate_inputs(inputs)
    result["issues"] = deepcopy(issues)
    result["unit_checks"] = _unit_checks(inputs)
    result["status"] = "blocked" if issues else "proposed"
    if not issues:
        return result

    # A failed validation makes the overall totals unknowable. Null only the
    # affected labor/item amounts where the quote carries a traceable reference.
    result["subtotal"] = result["tax"] = result["total"] = None
    labor_failed = any(issue["path"].startswith(("labor", "labor_rate")) for issue in issues)
    failed_item_indices = {
        int(issue["path"].split(".")[1])
        for issue in issues
        if issue["path"].startswith("items.") and issue["path"].split(".")[1].isdigit()
    }
    items = inputs.get("items", []) if isinstance(inputs, dict) else []
    failed_ids = {
        items[i].get("item_id") for i in failed_item_indices
        if isinstance(items, list) and i < len(items) and isinstance(items[i], dict)
    }
    lines = result.get("lines", [])
    if isinstance(lines, list):
        for line in lines:
            if not isinstance(line, dict):
                continue
            if (labor_failed and line.get("kind") == "labor") or line.get("source_ref") in failed_ids:
                line["amount"] = None
    return result


def _unit_checks(inputs: Any) -> list[dict[str, Any]]:
    """Record the compared units and outcome for each input unit boundary."""
    if not isinstance(inputs, dict):
        return []
    checks: list[dict[str, Any]] = []
    rate = inputs.get("labor_rate")
    basis = rate.get("basis", []) if isinstance(rate, dict) else []
    if isinstance(basis, list):
        for index, entry in enumerate(basis):
            if not isinstance(entry, dict):
                continue
            left = entry.get("unit")
            normalized = _unit_key(left)
            checks.append({
                "left_unit": left,
                "right_unit": "円/人時",
                "status": "matched" if normalized == "円/人時" else "mismatch",
                "confirmed_by": None,
                "source_ref": entry.get("source_ref", f"labor_rate.basis.{index}"),
            })
    items = inputs.get("items", [])
    if isinstance(items, list):
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            left = item.get("quantity_unit")
            right = item.get("unit")
            matched = _unit_key(left) is not None and _unit_key(left) == _unit_key(right)
            checks.append({
                "left_unit": left,
                "right_unit": right,
                "status": "matched" if matched else "mismatch",
                "confirmed_by": None,
                "source_ref": item.get("item_id", f"items.{index}"),
            })
    return checks
