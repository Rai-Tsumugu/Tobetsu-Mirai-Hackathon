"""P01: calculate labor price bands from person-hours and the approved rate."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from .common import add_ranges
from .p02 import calculate_billable_person_hours

BANDS = ("low", "typical", "high")


def _decimal(value, label):
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} is required and must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{label} must be numeric") from None
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    if result < 0:
        raise ValueError(f"{label} must not be negative")
    return result


def _json_number(value):
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def apply(quote: dict, inputs: dict) -> dict:
    """Return quote with one labor-total line, validating all P01 inputs."""
    if not isinstance(quote, dict) or not isinstance(inputs, dict):
        raise ValueError("quote and inputs must be objects")
    labor = inputs.get("labor")
    rate = inputs.get("labor_rate")
    if not isinstance(labor, dict) or not isinstance(rate, dict):
        raise ValueError("labor and labor_rate are required")
    unknowns = labor.get("unknowns", [])
    if not isinstance(unknowns, list) or unknowns:
        raise ValueError("labor.unknowns must be empty before P01 calculation")
    hours = labor.get("person_hours")
    if not isinstance(hours, dict):
        raise ValueError("labor.person_hours is required")
    parsed_hours = {}
    for band in BANDS:
        if band not in hours:
            raise ValueError(f"labor.person_hours.{band} is required")
        parsed_hours[band] = _decimal(hours[band], f"labor.person_hours.{band}")
    if not parsed_hours["low"] <= parsed_hours["typical"] <= parsed_hours["high"]:
        raise ValueError("labor.person_hours bands must satisfy low <= typical <= high")

    breakdown = labor.get("breakdown")
    if not isinstance(breakdown, list) or not breakdown:
        raise ValueError("labor.breakdown must contain at least one operation")
    all_hours = []
    excluded_operations = []
    for entry in breakdown:
        if not isinstance(entry, dict):
            raise ValueError("each labor.breakdown item must be an object")
        if not isinstance(entry.get("operation"), str) or not entry["operation"].strip():
            raise ValueError("labor.breakdown.operation is required")
        row_hours = entry.get("hours")
        if not isinstance(row_hours, dict) or set(row_hours) != set(BANDS):
            raise ValueError("labor.breakdown.hours must contain all three bands")
        parsed_row_hours = {band: _decimal(row_hours[band], f"breakdown.hours.{band}") for band in BANDS}
        if not parsed_row_hours["low"] <= parsed_row_hours["typical"] <= parsed_row_hours["high"]:
            raise ValueError("labor.breakdown.hours bands must be ordered")
        all_hours.append({band: _json_number(parsed_row_hours[band]) for band in BANDS})
        status = entry.get("status", "proposed")
        if status not in {"proposed", "observed", "confirmed", "conditional", "approved_nonbillable"}:
            raise ValueError("unknown or unapproved labor status must be resolved")
        if status in ("nonbillable", "excluded", "not_billable", "non_billable"):
            raise ValueError("unapproved nonbillable labor operation cannot be excluded")
        if status == "approved_nonbillable":
            required = (entry.get("reason"), entry.get("approved_by"), entry.get("billing_selection_ref"))
            if not all(isinstance(value, str) and value.strip() for value in required):
                raise ValueError("approved nonbillable operation requires reason, approver, and billing_selection_ref")
            excluded_operations.append({
                "operation_ref": entry["operation"],
                "source_ref": entry.get("source_ref", labor.get("source_ref", labor.get("labor_id"))),
                "person_hours": deepcopy(entry["hours"]),
                "billing_selection_ref": entry["billing_selection_ref"],
                "reason": entry["reason"],
                "approved_by": entry["approved_by"],
            })
    summed_hours = add_ranges(*all_hours)
    if any(_decimal(summed_hours[band], f"breakdown.sum.{band}") != parsed_hours[band] for band in BANDS):
        raise ValueError("labor.breakdown hours must sum to labor.person_hours in every band")
    billable_hours = calculate_billable_person_hours(breakdown)
    parsed_billable_hours = {band: _decimal(billable_hours[band], f"billable_hours.{band}") for band in BANDS}
    if not parsed_billable_hours["low"] <= parsed_billable_hours["typical"] <= parsed_billable_hours["high"]:
        raise ValueError("billable person-hour bands must be ordered")

    if "yen_per_person_hour" not in rate:
        raise ValueError("labor_rate.yen_per_person_hour is required")
    yen_per_hour = _decimal(rate["yen_per_person_hour"], "labor_rate.yen_per_person_hour")
    basis = rate.get("basis")
    if not isinstance(basis, list) or not basis or not any(
        isinstance(entry, dict) and any(v not in (None, "") for v in entry.values())
        for entry in basis
    ):
        raise ValueError("labor_rate basis is required")

    if not any(isinstance(entry, dict) and "".join(str(entry.get("unit", "")).split()) == "円/人時" for entry in basis):
        raise ValueError("labor_rate basis must include 円/人時 evidence")
    for entry in basis:
        if not isinstance(entry, dict) or "".join(str(entry.get("unit", "")).split()) != "円/人時":
            raise ValueError('labor_rate basis must use 円/人時')
        if _decimal(entry.get('value'), 'labor_rate.basis.value') != yen_per_hour:
            raise ValueError('labor_rate basis rate must match yen_per_person_hour')
    result = deepcopy(quote)
    lines = result.setdefault("lines", [])
    if not isinstance(lines, list):
        raise ValueError("quote.lines must be a list")
    # Replacement makes repeated application deterministic and prevents duplication.
    lines[:] = [line for line in lines if not (isinstance(line, dict) and line.get("line_id") == "labor-total")]
    amount = {band: _json_number(parsed_billable_hours[band] * yen_per_hour) for band in BANDS}
    billing_selection = {
        "billed_person_hours": {band: _json_number(parsed_billable_hours[band]) for band in BANDS},
        "excluded_operations": excluded_operations,
        "reason": "Approved nonbillable operations excluded; no elapsed-time or u_period charge applied",
        "approved_by": sorted({entry["approved_by"] for entry in breakdown if entry.get("status") == "approved_nonbillable"}),
        "u_period_applied": False,
    }
    snapshot = {"labor": deepcopy(labor), "labor_rate": deepcopy(rate), "billing_selection": deepcopy(billing_selection)}
    lines.append({
        "line_id": "labor-total",
        "kind": "labor",
        "category": "labor",
        "description": "工賃",
        "quantity_range": {band: _json_number(parsed_billable_hours[band]) for band in BANDS},
        "unit": "人時",
        "unit_price_range": {band: _json_number(yen_per_hour) for band in BANDS},
        "amount": amount,
        "source_system": "labor_engine",
        "source_ref": labor.get("source_ref", labor.get("labor_id", "labor")),
        "snapshot": snapshot,
        "reason": "labor.person_hours × labor_rate.yen_per_person_hour; elapsed_hours is excluded",
        "status": "calculated",
    })
    result["billing_selection"] = deepcopy(billing_selection)
    return result
