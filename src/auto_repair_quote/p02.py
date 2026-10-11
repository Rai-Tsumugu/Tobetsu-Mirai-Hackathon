"""P02: expand aggregate labor into auditable, per-operation quote lines."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .common import BANDS, QuoteError, add_ranges, make_line, multiply_ranges, number, range_value


_LINE_PREFIX = "labor-breakdown:"
_NONBILLABLE_STATUS = "approved_nonbillable"


def calculate_billable_person_hours(breakdown: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum billable operation hours, excluding only approved nonbillable rows."""
    hours = [item["hours"] for item in breakdown if item.get("status", "proposed") != _NONBILLABLE_STATUS]
    return add_ranges(*hours) if hours else {band: 0 for band in BANDS}


def apply(quote: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Replace a P01 aggregate labor row with one priced row per breakdown item.

    Breakdown hours are treated as the source of the labor total. The total is
    checked against ``labor.person_hours`` before any quote changes are made.
    """
    if not isinstance(quote, dict) or not isinstance(inputs, dict):
        raise QuoteError("quote and inputs must be objects")
    labor = inputs.get("labor")
    rate = inputs.get("labor_rate")
    if not isinstance(labor, dict) or not isinstance(rate, dict):
        raise QuoteError("labor and labor_rate are required")
    unknowns = labor.get("unknowns", [])
    if not isinstance(unknowns, list) or unknowns:
        raise QuoteError("labor.unknowns must be an empty list before P02 calculation")

    total_hours = range_value(labor.get("person_hours"))
    if "yen_per_person_hour" not in rate:
        raise QuoteError("labor_rate.yen_per_person_hour is required")
    parsed_rate = number(rate["yen_per_person_hour"])
    basis = rate.get("basis")
    if not isinstance(basis, list) or not basis or not any(
        isinstance(entry, dict) and any(value not in (None, "") for value in entry.values())
        for entry in basis
    ):
        raise QuoteError("labor_rate basis is required")

    breakdown = labor.get("breakdown")
    if not isinstance(breakdown, list) or not breakdown:
        raise QuoteError("labor.breakdown must contain at least one operation")

    parsed_items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(breakdown):
        if not isinstance(item, dict):
            raise QuoteError("each labor.breakdown item must be an object")
        operation = item.get("operation")
        if not isinstance(operation, str) or not operation.strip():
            raise QuoteError("labor.breakdown.operation is required")
        hours = range_value(item.get("hours"))
        source_ref = item.get("source_ref", labor.get("source_ref", labor.get("labor_id")))
        if source_ref is None or not isinstance(source_ref, (str, int)) or not str(source_ref).strip():
            # A deterministic item-local reference keeps every generated row traceable.
            source_ref = f"labor-breakdown-{index + 1}"
        source_ref = str(source_ref)
        identity = (operation.strip(), source_ref)
        if identity in seen:
            raise QuoteError(f"duplicate labor operation/source_ref: {identity!r}")
        seen.add(identity)
        status = item.get("status", "proposed")
        if status not in {"proposed", "observed", "confirmed", "conditional", "approved_nonbillable"}:
            raise QuoteError("unknown or unapproved labor status must be resolved")
        if not isinstance(status, str):
            raise QuoteError("labor.breakdown.status must be a string")
        reason = item.get("reason")
        approved_by = item.get("approved_by")
        billing_selection_ref = item.get("billing_selection_ref")
        if status == _NONBILLABLE_STATUS and not all(
            isinstance(value, str) and value.strip()
            for value in (reason, approved_by, billing_selection_ref)
        ):
            raise QuoteError(
                "approved_nonbillable operations require reason, approved_by, and billing_selection_ref"
            )
        parsed_items.append({
            "source": item, "hours": hours, "operation": operation.strip(),
            "source_ref": source_ref, "status": status, "reason": reason,
            "approved_by": approved_by, "billing_selection_ref": billing_selection_ref,
        })

    summed = add_ranges(*(entry["hours"] for entry in parsed_items))
    if any(number(summed[band]) != total_hours[band] for band in BANDS):
        raise QuoteError("labor.breakdown hours must sum to labor.person_hours in every band")
    billable_hours = calculate_billable_person_hours(parsed_items)

    result = deepcopy(quote)
    lines = result.setdefault("lines", [])
    if not isinstance(lines, list):
        raise QuoteError("quote.lines must be a list")
    # Remove the P01 aggregate row and this implementation's prior rows so
    # applying P02 repeatedly cannot double-bill.
    lines[:] = [
        line for line in lines
        if not (
            isinstance(line, dict)
            and (line.get("line_id") == "labor-total"
                 or (isinstance(line.get("line_id"), str) and line["line_id"].startswith(_LINE_PREFIX)))
        )
    ]

    excluded_operations = []
    for index, entry in enumerate(parsed_items, start=1):
        item = entry["source"]
        hours = entry["hours"]
        operation = entry["operation"]
        source_ref = entry["source_ref"]
        status = entry["status"]
        nonbillable = status == _NONBILLABLE_STATUS
        amount = {band: 0 for band in BANDS} if nonbillable else multiply_ranges(hours, parsed_rate)
        billing_selection = None
        if nonbillable:
            billing_selection = {
                "operation_ref": operation,
                "source_ref": source_ref,
                "person_hours": {band: float(value) if value != value.to_integral_value() else int(value) for band, value in hours.items()},
                "billing_selection_ref": entry["billing_selection_ref"],
                "reason": entry["reason"],
                "approved_by": entry["approved_by"],
            }
            excluded_operations.append(deepcopy(billing_selection))
        snapshot = {
            "operation": deepcopy(item),
            "labor_rate": deepcopy(rate),
        }
        if billing_selection is not None:
            snapshot["billing_selection"] = deepcopy(billing_selection)
        line = make_line(
            line_id=f"{_LINE_PREFIX}{index}",
            kind="labor",
            category="labor",
            description=operation,
            quantity_range=hours,
            unit="人時",
            unit_price_range={band: parsed_rate for band in BANDS},
            amount=amount,
            source_system="labor_engine",
            source_ref=source_ref,
            snapshot=snapshot,
            reason=str(entry["reason"] or "工程別人時 × 承認済み円/人時単価"),
            status=status,
        )
        line["billing_selection_ref"] = entry["billing_selection_ref"]
        lines.append(line)
    result["billing_selection"] = {
        "billed_person_hours": billable_hours,
        "excluded_operations": excluded_operations,
    }
    return result
