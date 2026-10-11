"""P28: query the append-only communication ledger by quote version."""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any
from uuid import UUID

from .common import BANDS, QuoteError, number
from .p18 import record_communication


def communication_ledger(store: Any, quote_id: str) -> list[dict[str, Any]]:
    """Return validated communication snapshots for a quote, oldest first."""
    if not isinstance(quote_id, str) or not quote_id.strip():
        raise QuoteError("quote_id is required")

    records = store.list_communications(quote_id)
    result = []
    for record in records:
        if not isinstance(record, dict) or record.get("quote_id") != quote_id:
            raise QuoteError("communication quote_id does not match ledger")
        version = record.get("quote_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise QuoteError("communication quote_version must be a positive integer")
        try:
            quote = store.get_quote(quote_id, version)
        except (ValueError, KeyError) as exc:
            raise QuoteError("communication references a missing quote version") from exc
        if quote.get("quote_id") != quote_id or quote.get("quote_version") != version:
            raise QuoteError("communication quote version reference is invalid")
        if record.get("selected_band") not in BANDS:
            raise QuoteError("communication selected_band is invalid")
        amount = record.get("communicated_amount")
        if isinstance(amount, bool):
            raise QuoteError("communicated_amount must be finite")
        try:
            parsed = number(amount)
        except (TypeError, ValueError, QuoteError) as exc:
            raise QuoteError("communicated_amount must be finite") from exc
        if not parsed.is_finite() or not math.isfinite(float(parsed)):
            raise QuoteError("communicated_amount must be finite")
        _validate_ref(record.get("customer_ref"), "C-", "customer_ref")
        _validate_ref(record.get("vehicle_ref"), "V-", "vehicle_ref")
        _validate_ref(record.get("operator"), "operator-", "operator")
        result.append(deepcopy(record))
    return result


def append_communication(store: Any, quote: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Append one immutable communication using P18's validated writer."""
    return deepcopy(record_communication(store, deepcopy(quote), deepcopy(data)))


def query_communications(
    store: Any,
    quote_id: str,
    quote_version: int | None = None,
    customer_ref: str | None = None,
    vehicle_ref: str | None = None,
) -> list[dict[str, Any]]:
    """Filter ledger snapshots by exact references, preserving communicated amounts."""
    records = communication_ledger(store, quote_id)
    if quote_version is not None:
        if isinstance(quote_version, bool) or not isinstance(quote_version, int) or quote_version < 1:
            raise QuoteError("quote_version must be a positive integer")
        records = [row for row in records if row["quote_version"] == quote_version]
    if customer_ref is not None:
        records = [row for row in records if row["customer_ref"] == customer_ref]
    if vehicle_ref is not None:
        records = [row for row in records if row["vehicle_ref"] == vehicle_ref]
    return deepcopy(records)


def _validate_ref(value: Any, prefix: str, field: str) -> None:
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) <= len(prefix):
        raise QuoteError(f"{field} must be an anonymous reference")
    suffix = value[len(prefix):]
    if prefix in {"C-", "V-"}:
        sequence = re.fullmatch(r"(?:DEMO-)?[0-9]{1,6}", suffix)
        try:
            UUID(suffix)
            opaque_id = True
        except ValueError:
            opaque_id = False
        if not sequence and not opaque_id:
            raise QuoteError(f"{field} must be an opaque UUID or short anonymous sequence")
    if not all(char.isascii() and (char.isalnum() or char in "-_") for char in suffix):
        raise QuoteError(f"{field} must be an anonymous reference")
