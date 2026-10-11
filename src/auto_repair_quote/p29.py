"""P29: append an approval event for a quote change."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from .common import QuoteError
from .p26 import compare_versions


_ALLOWED_DATA_KEYS = {
    "quote_id", "from_version", "to_version", "trigger_ref", "operator",
    "condition_note", "ack_status", "communicated_amount", "communication_id",
}


def record_change(store: Any, data: Mapping[str, Any]) -> dict[str, Any]:
    """Persist a sanitized, append-only event between two stored quote versions."""
    if not isinstance(data, Mapping):
        raise QuoteError("data must be an object")
    clean = {key: deepcopy(data[key]) for key in _ALLOWED_DATA_KEYS if key in data}
    for key in ("quote_id", "trigger_ref", "operator", "condition_note", "ack_status"):
        value = clean.get(key)
        if not isinstance(value, str) or not value.strip():
            raise QuoteError(f"{key} is required")
    if clean["ack_status"] not in {"pending", "accepted", "declined"}:
        raise QuoteError("ack_status must be pending, accepted, or declined")
    for key in ("from_version", "to_version"):
        value = clean.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise QuoteError(f"{key} must be a positive integer")
    if clean["to_version"] <= clean["from_version"]:
        raise QuoteError("to_version must be greater than from_version")

    with store.transaction():
        try:
            old_quote = store.get_quote(clean["quote_id"], clean["from_version"])
            new_quote = store.get_quote(clean["quote_id"], clean["to_version"])
        except (KeyError, ValueError) as exc:
            raise QuoteError("both persisted quote versions are required") from exc
        if old_quote.get("quote_id") != new_quote.get("quote_id"):
            raise QuoteError("quote versions must belong to the same quote")
        diff = compare_versions(old_quote, new_quote)

        communication = None
        communication_id = clean.get("communication_id")
        if clean["ack_status"] == "accepted" and not communication_id:
            raise QuoteError("accepted changes require a saved communication_id")
        if communication_id is not None:
            if not isinstance(communication_id, str) or not communication_id.strip():
                raise QuoteError("communication_id must be a non-empty string")
            communication = next((item for item in store.list_communications(clean["quote_id"])
                                  if item.get("communication_id") == communication_id), None)
            if communication is None:
                raise QuoteError("communication_id must reference a saved communication")
            if communication.get("quote_id") != clean["quote_id"] or communication.get("quote_version") != clean["to_version"]:
                raise QuoteError("communication must reference the new quote version")
            if communication.get("condition_note") != clean["condition_note"]:
                raise QuoteError("communication condition must match the change event")
            if communication.get("customer_ref") != new_quote.get("customer_ref") or communication.get("vehicle_ref") != new_quote.get("vehicle_ref"):
                raise QuoteError("communication customer references must match the new quote")
            if "communicated_amount" in clean and clean["communicated_amount"] != communication.get("communicated_amount"):
                raise QuoteError("communicated_amount must match the saved communication")
            clean["communicated_amount"] = deepcopy(communication.get("communicated_amount"))
        elif "communicated_amount" in clean:
            raise QuoteError("communicated_amount requires a saved communication")

        if clean["ack_status"] == "accepted" and communication is None:
            raise QuoteError("accepted changes require a matching saved communication")
        event = {
            "event_id": str(uuid4()),
            "quote_id": clean["quote_id"],
            "from_version": clean["from_version"],
            "to_version": clean["to_version"],
            "trigger_ref": clean["trigger_ref"],
            "delta_lines": {key: deepcopy(diff[key]) for key in ("added", "removed", "changed")},
            "amount_delta": deepcopy(diff["amount_delta"]),
            "condition_note": clean["condition_note"],
            "operator": clean["operator"],
            "ack_status": clean["ack_status"],
            "work_status": "pending" if clean["ack_status"] == "pending" else ("blocked" if clean["ack_status"] == "declined" else "continue"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if "communicated_amount" in clean:
            event["communicated_amount"] = deepcopy(clean["communicated_amount"])
        if communication is not None:
            event["communication_id"] = communication_id
        return store.append_change_event(event)


def list_change_events(store: Any, quote_id: str) -> list[dict[str, Any]]:
    """Return a detached list of append-only change events for a quote."""
    return deepcopy(store.list_change_events(quote_id))
