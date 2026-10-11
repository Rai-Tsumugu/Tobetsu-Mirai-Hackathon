"""P30: prepare confirmed quote data for a document renderer."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .common import BANDS, QuoteError, _json_number, number, range_value


def document_payload(quote: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached, validated document payload without recalculating it."""
    if not isinstance(quote, Mapping):
        raise QuoteError("quote must be an object")
    if quote.get("status") != "confirmed":
        raise QuoteError("only confirmed quotes can be rendered")
    if quote.get("unknowns"):
        raise QuoteError("quotes with unresolved unknowns cannot be rendered")

    quote_id = quote.get("quote_id")
    version = quote.get("quote_version")
    if not isinstance(quote_id, str) or not quote_id.strip():
        raise QuoteError("quote_id is required")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise QuoteError("quote_version must be a positive integer")

    selected_band = quote.get("selected_band")
    confirmed_by = quote.get("confirmed_by")
    if selected_band not in BANDS:
        raise QuoteError("selected_band must be low, typical, or high")
    if not isinstance(confirmed_by, str) or not confirmed_by.strip():
        raise QuoteError("confirmed_by is required")
    confirmation = quote.get("confirmation")
    if not isinstance(confirmation, Mapping):
        raise QuoteError("matching confirmation record is required")
    if confirmation.get("selected_band") != selected_band:
        raise QuoteError("confirmation selected_band must match quote")
    if confirmation.get("confirmed_by") != confirmed_by:
        raise QuoteError("confirmation confirmed_by must match quote")

    try:
        subtotal = range_value(quote.get("subtotal"))
        tax = range_value(quote.get("tax"))
        total = range_value(quote.get("total"))
    except (QuoteError, TypeError) as exc:
        raise QuoteError("subtotal, tax, and total must be complete ordered ranges") from exc
    for band in BANDS:
        if subtotal[band] + tax[band] != total[band]:
            raise QuoteError(f"subtotal plus tax must match total for {band}")
    # Keep recorded ranges as provided; validation above does not derive or replace them.
    for key in ("lines", "reasons", "conditions"):
        if not isinstance(quote.get(key), list):
            raise QuoteError(f"quote.{key} must be a list")
    if "sources" in quote:
        sources = quote["sources"]
        if not isinstance(sources, (list, dict)):
            raise QuoteError("quote.sources must be a list or object")
    else:
        sources = [
            {key: deepcopy(line[key]) for key in ("source_system", "source_ref", "snapshot") if key in line}
            for line in quote["lines"]
            if isinstance(line, Mapping) and any(key in line for key in ("source_system", "source_ref", "snapshot"))
        ]

    proposed_amount = number(confirmation.get("proposed_amount", total[selected_band]))
    nested_final = confirmation.get("final_amount")
    top_final = quote.get("final_amount")
    if nested_final is None and top_final is None:
        raise QuoteError("confirmed final_amount is required")
    final_amount = number(nested_final if nested_final is not None else top_final)
    if nested_final is not None and top_final is not None and number(top_final) != final_amount:
        raise QuoteError("quote final_amount must match confirmation")
    if number(total[selected_band]) != proposed_amount:
        raise QuoteError("confirmation proposed_amount must match selected total")

    override_reason = confirmation.get("override_reason", quote.get("override_reason"))
    if override_reason is not None and (not isinstance(override_reason, str) or not override_reason.strip()):
        raise QuoteError("override_reason must be a non-empty string when provided")
    amount_adjustment = _json_number(final_amount - proposed_amount)
    if final_amount != proposed_amount and not override_reason:
        raise QuoteError("an overridden final_amount requires override_reason")
    if quote.get("override_reason") is not None and confirmation.get("override_reason") is not None and quote["override_reason"] != confirmation["override_reason"]:
        raise QuoteError("quote and confirmation override_reason must match")

    confirmed_at = quote.get("confirmed_at", confirmation.get("confirmed_at"))
    if not isinstance(confirmed_at, str) or not confirmed_at.strip():
        raise QuoteError("confirmed_at is required")
    if quote.get("confirmed_at") and confirmation.get("confirmed_at") and quote["confirmed_at"] != confirmation["confirmed_at"]:
        raise QuoteError("quote and confirmation confirmed_at must match")

    return {
        "quote_id": quote_id,
        "quote_version": version,
        "lines": deepcopy(quote["lines"]),
        "subtotal": deepcopy(quote["subtotal"]),
        "tax": deepcopy(quote["tax"]),
        "total": deepcopy(quote["total"]),
        "selected_band": selected_band,
        "selected_subtotal": _json_number(subtotal[selected_band]),
        "selected_tax": _json_number(tax[selected_band]),
        "selected_total": _json_number(total[selected_band]),
        "reasons": deepcopy(quote["reasons"]),
        "conditions": deepcopy(quote["conditions"]),
        "confirmed_by": confirmed_by,
        "confirmed_at": confirmed_at,
        "override_reason": deepcopy(override_reason),
        "sources": deepcopy(sources),
        "final_amount": _json_number(final_amount),
        "proposed_amount": _json_number(proposed_amount),
        "amount_adjustment": amount_adjustment,
        "tax_allocation_note": "確定額の税配分は未確認。帳票側で税内訳を再計算しない。これは見積データであり請求書ではない。",
    }
