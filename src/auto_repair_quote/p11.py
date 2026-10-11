"""P11: collect estimate conditions, unknowns, and excluded work."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .common import QuoteError

_EXCLUDED = {"excluded", "nonbillable", "non_billable", "not_billable", "approved_nonbillable"}


def conditions_panel(quote: Mapping[str, Any], inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return customer-facing conditions with internal approval and customer ack separate."""
    if not isinstance(quote, Mapping):
        raise QuoteError("quote must be an object")
    if not isinstance(inputs, Mapping):
        raise QuoteError("inputs must be an object")

    rows: list[dict[str, Any]] = []
    prior = quote.get("conditions", [])
    if not isinstance(prior, list):
        raise QuoteError("quote.conditions must be a list")
    for index, entry in enumerate(prior):
        rows.append(_condition(entry, f"quote.conditions.{index}"))

    raw_conditions = inputs.get("conditions", [])
    if not isinstance(raw_conditions, list):
        raise QuoteError("inputs.conditions must be a list")
    for index, entry in enumerate(raw_conditions):
        rows.append(_condition(entry, f"conditions.{index}"))

    labor = inputs.get("labor", {})
    if not isinstance(labor, Mapping):
        raise QuoteError("inputs.labor must be an object")
    unknowns = labor.get("unknowns", [])
    if not isinstance(unknowns, list):
        raise QuoteError("labor.unknowns must be a list")
    for index, entry in enumerate(unknowns):
        rows.append(_condition(entry, f"labor.unknowns.{index}", status="unknown", ack_required=True))

    breakdown = labor.get("breakdown", [])
    if not isinstance(breakdown, list):
        raise QuoteError("labor.breakdown must be a list")
    for index, entry in enumerate(breakdown):
        if not isinstance(entry, Mapping):
            raise QuoteError(f"labor.breakdown.{index} must be an object")
        status = str(entry.get("status", "proposed")).casefold()
        if status in _EXCLUDED:
            rows.append(_condition(entry, f"labor.breakdown.{index}", status="excluded", ack_required=True))
        elif status in {"conditional", "condition", "conditional_proposed"}:
            rows.append(_condition(entry, f"labor.breakdown.{index}", status="conditional", ack_required=True))

    return _dedupe(rows)


def apply(quote: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Copy quote and append conditions and explanatory reasons idempotently."""
    if not isinstance(quote, dict):
        raise QuoteError("quote must be an object")
    if not isinstance(inputs, dict):
        raise QuoteError("inputs must be an object")
    result = deepcopy(quote)
    conditions = conditions_panel(result, inputs)
    result["conditions"] = conditions

    reasons = result.get("reasons", [])
    if not isinstance(reasons, list):
        raise QuoteError("quote.reasons must be a list")
    appended = deepcopy(reasons)
    seen = {_reason_key(value) for value in appended}
    candidates: list[Any] = []
    for condition in conditions:
        candidates.append(condition["text"])
    labor = inputs.get("labor", {})
    if isinstance(labor, Mapping):
        for entry in labor.get("breakdown", []) if isinstance(labor.get("breakdown", []), list) else []:
            if not isinstance(entry, Mapping):
                continue
            # Keep ordinary fixture work explanations visible in the quote reasons too.
            explanation = entry.get("reason") or entry.get("operation")
            if _nonempty(explanation):
                candidates.append(explanation)
    for reason in candidates:
        key = _reason_key(reason)
        if key and key not in seen:
            appended.append(deepcopy(reason))
            seen.add(key)
    result["reasons"] = appended
    return result


def _condition(value: Any, fallback_ref: str, *, status: str | None = None, ack_required: bool | None = None) -> dict[str, Any]:
    if isinstance(value, str):
        raw: Mapping[str, Any] = {"text": value}
    elif isinstance(value, Mapping):
        raw = value
    else:
        raise QuoteError(f"condition at {fallback_ref} must be text or an object")
    text = raw.get("text") or raw.get("reason") or raw.get("operation")
    if not _nonempty(text):
        raise QuoteError(f"condition at {fallback_ref} requires text")
    resolved_status = status or raw.get("status") or "unconfirmed"
    required = ack_required if ack_required is not None else raw.get("customer_ack_required", True)
    if not isinstance(required, bool):
        raise QuoteError(f"condition at {fallback_ref}.customer_ack_required must be boolean")
    ack_status = raw.get("customer_ack_status")
    if ack_status is None:
        ack_status = "pending" if required else "not_required"
    if not isinstance(ack_status, str) or not ack_status.strip():
        raise QuoteError(f"condition at {fallback_ref}.customer_ack_status must be non-empty text")
    bands = raw.get("bands", raw.get("hours"))
    return {
        "text": deepcopy(text),
        "source_ref": deepcopy(raw.get("source_ref", fallback_ref)),
        "status": deepcopy(resolved_status),
        "customer_ack_required": required,
        "approved_by": deepcopy(raw.get("approved_by")),
        "customer_ack_status": ack_status,
        **({"bands": deepcopy(bands)} if bands is not None else {}),
    }


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    indexes: dict[tuple[str, str, str], int] = {}
    for row in rows:
        key = (_reason_key(row["text"]), str(row["source_ref"]), str(row["status"]))
        if key not in indexes:
            indexes[key] = len(result)
            result.append(row)
            continue
        old = result[indexes[key]]
        # An explicit approval is retained, but it never changes customer acknowledgement.
        if old.get("approved_by") is None and row.get("approved_by") is not None:
            old["approved_by"] = deepcopy(row["approved_by"])
        if row.get("customer_ack_status") not in (None, "pending"):
            old["customer_ack_status"] = row["customer_ack_status"]
        if "bands" not in old and "bands" in row:
            old["bands"] = deepcopy(row["bands"])
    return result


def _reason_key(value: Any) -> str:
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
