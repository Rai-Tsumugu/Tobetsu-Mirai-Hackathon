"""P15: create and explicitly persist immutable revised quote versions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping

from .common import QuoteError


_RESET_FIELDS = ("selected_band", "confirmed_by", "confirmation", "override_reason")


def revise_quote(
    store: Any,
    quote_id: str,
    from_version: int,
    inputs: Mapping[str, Any],
    calculate: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]:
    """Recalculate changed inputs as a new proposal, without saving it."""
    if not isinstance(quote_id, str) or not quote_id.strip():
        raise QuoteError("quote_id is required")
    if isinstance(from_version, bool) or not isinstance(from_version, int) or from_version < 1:
        raise QuoteError("from_version must be a positive integer")
    if not isinstance(inputs, Mapping):
        raise QuoteError("inputs must be an object")
    if not callable(calculate):
        raise QuoteError("calculate must be callable")

    source = store.get_quote(quote_id, from_version)
    if source.get("quote_id") != quote_id or source.get("quote_version") != from_version:
        raise QuoteError("source quote does not match requested quote version")

    changed_inputs = deepcopy(dict(inputs))
    input_quote_id = changed_inputs.get("quote_id")
    if input_quote_id is not None and input_quote_id != quote_id:
        raise QuoteError("inputs quote_id does not match requested quote")
    changed_inputs["quote_id"] = quote_id
    latest = store.get_quote(quote_id)
    latest_version = latest.get("quote_version")
    if isinstance(latest_version, bool) or not isinstance(latest_version, int) or latest_version < 1:
        raise QuoteError("latest quote has an invalid version")

    changed_inputs["quote_version"] = latest_version + 1
    changed_inputs["parent_version"] = from_version
    calculated = calculate(deepcopy(changed_inputs))
    if not isinstance(calculated, Mapping):
        raise QuoteError("calculate must return a quote object")
    if calculated.get("quote_id") not in (None, quote_id):
        raise QuoteError("calculated quote_id does not match requested quote")

    result = deepcopy(dict(calculated))
    result.update(
        quote_id=quote_id,
        quote_version=latest_version + 1,
        parent_version=from_version,
    )
    result["metadata"] = deepcopy(result.get("metadata") or {})
    result["metadata"]["input_snapshot"] = deepcopy(changed_inputs)
    result["status"] = "blocked" if calculated.get("status") == "blocked" else "proposed"
    for field in _RESET_FIELDS:
        result[field] = None
    return result


def save_version(store: Any, quote: Mapping[str, Any]) -> dict[str, Any]:
    """Insert a quote snapshot once; the store rejects version collisions."""
    if not isinstance(quote, Mapping):
        raise QuoteError("quote must be an object")
    quote_id = quote.get("quote_id")
    quote_version = quote.get("quote_version")
    if not isinstance(quote_id, str) or not quote_id.strip():
        raise QuoteError("quote_id is required")
    if isinstance(quote_version, bool) or not isinstance(quote_version, int) or quote_version < 1:
        raise QuoteError("quote_version must be a positive integer")
    return store.save_quote(deepcopy(dict(quote)))
