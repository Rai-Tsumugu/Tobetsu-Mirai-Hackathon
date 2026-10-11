"""P18: append a manual record of the amount and conditions communicated."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Any, Mapping
from uuid import uuid4, UUID
import re

from .common import BANDS, QuoteError, number


_ALLOWED_DATA_KEYS = {
    "selected_band", "customer_ref", "vehicle_ref", "operator",
    "condition_note", "communicated_amount",
}


def record_communication(store: Any, quote: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    """Append a communication against the exact persisted quote version.

    Unknown data (including API-level ``inputs`` and personal information) is
    deliberately discarded. The quote snapshot is only read and never edited.
    """
    if not isinstance(quote, Mapping):
        raise QuoteError("quote must be an object")
    if not isinstance(data, Mapping):
        raise QuoteError("data must be an object")

    quote_id = quote.get("quote_id")
    quote_version = quote.get("quote_version")
    if not isinstance(quote_id, str) or not quote_id.strip():
        raise QuoteError("quote_id is required")
    if isinstance(quote_version, bool) or not isinstance(quote_version, int) or quote_version < 1:
        raise QuoteError("quote_version must be a positive integer")
    persisted = store.get_quote(quote_id, quote_version)
    if persisted.get("quote_id") != quote_id or persisted.get("quote_version") != quote_version:
        raise QuoteError("quote does not match persisted quote version")
    if dict(quote) != persisted:
        raise QuoteError("quote differs from persisted quote version")
    if persisted.get("status") == "blocked":
        raise QuoteError("blocked quotes cannot be communicated")

    clean = {key: deepcopy(data[key]) for key in _ALLOWED_DATA_KEYS if key in data}
    for key in ("selected_band", "customer_ref", "vehicle_ref", "operator", "condition_note"):
        if key not in clean:
            raise QuoteError(f"{key} is required")

    band = clean["selected_band"]
    if band not in BANDS:
        raise QuoteError("selected_band must be low, typical, or high")
    _require_anonymous_ref(clean["customer_ref"], "C-", "customer_ref")
    _require_anonymous_ref(clean["vehicle_ref"], "V-", "vehicle_ref")
    _require_anonymous_ref(clean["operator"], "operator-", "operator")
    if not isinstance(clean["condition_note"], str) or not clean["condition_note"].strip():
        raise QuoteError("condition_note is required")

    if re.search(r"(?:0\d[\d -]{8,}\d)|(?:\b\d{3}[ -]\d{3}[ -]\d{4}\b)|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", clean["condition_note"]):
        raise QuoteError("condition_note must not contain phone numbers or email addresses")
    confirmation = persisted.get('confirmation')
    if persisted.get('status') == 'confirmed':
        if band != persisted.get('selected_band'):
            raise QuoteError('communication band must match the confirmed quote')
        if not isinstance(confirmation, Mapping) or confirmation.get('final_amount') is None:
            raise QuoteError('confirmed final amount is required')
        amount = _json_number(number(confirmation['final_amount']))
        if 'communicated_amount' in clean and number(clean['communicated_amount']) != number(amount):
            raise QuoteError('a different communicated amount requires a new quote version')
    elif "communicated_amount" in clean:
        amount = _json_number(number(clean["communicated_amount"]))
    else:
        confirmation = persisted.get("confirmation")
        if persisted.get("status") == "confirmed" and isinstance(confirmation, Mapping) and confirmation.get("final_amount") is not None:
            amount = _json_number(number(confirmation["final_amount"]))
        else:
            total = persisted.get("total")
            if not isinstance(total, Mapping) or band not in total or total[band] is None:
                raise QuoteError("selected quote amount is unknown")
            amount = _json_number(number(total[band]))

    record = {
        "communication_id": str(uuid4()),
        "quote_id": quote_id,
        "quote_version": quote_version,
        "customer_ref": clean["customer_ref"],
        "vehicle_ref": clean["vehicle_ref"],
        "selected_band": band,
        "communicated_amount": amount,
        "condition_note": clean["condition_note"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operator": clean["operator"],
    }
    return store.append_communication(record)


def _require_anonymous_ref(value: Any, prefix: str, field: str) -> None:
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) <= len(prefix):
        raise QuoteError(f"{field} must be an anonymous reference beginning with {prefix}")
    suffix = value[len(prefix):]
    if prefix in {"C-", "V-"}:
        demo_or_sequence = re.fullmatch(r"(?:DEMO-)?[0-9]{1,6}", suffix)
        try:
            UUID(suffix)
            opaque_id = True
        except ValueError:
            opaque_id = False
        if not demo_or_sequence and not opaque_id:
            raise QuoteError(f"{field} must be an opaque UUID or short anonymous sequence")
    if not all(char.isascii() and (char.isalnum() or char in "-_") for char in suffix):
        raise QuoteError(f"{field} must be an anonymous reference")


def _json_number(value):
    if value == value.to_integral_value():
        return int(value)
    result = float(value)
    if not math.isfinite(result):
        raise QuoteError("amount must remain finite as a stored number")
    return result
