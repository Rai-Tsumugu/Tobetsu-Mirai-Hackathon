"""P14: confirm a proposed quote using an explicit band and any override."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from .common import BANDS, QuoteError, _json_number, number, range_value


def confirm_quote(
    quote: Mapping[str, Any],
    selected_band: str,
    confirmed_by: str,
    final_amount: Any = None,
    override_reason: str | None = None,
) -> dict[str, Any]:
    """Return a confirmed copy while retaining the proposed total range.

    ``final_amount`` is optional; when omitted, the explicitly selected band is
    used. Any supplied amount that changes that proposal requires a reason,
    including changes that remain inside the proposed range.
    """
    if not isinstance(quote, Mapping):
        raise QuoteError("quote must be an object")
    if quote.get("status") == "confirmed" or quote.get("confirmation") is not None:
        raise QuoteError("quote is already confirmed")
    status = quote.get("status")
    if isinstance(status, str) and status in {"blocked", "unknown"}:
        raise QuoteError("blocked or unknown quotes cannot be confirmed")
    if quote.get("unknowns"):
        raise QuoteError("quote unknowns must be resolved before confirmation")
    if selected_band not in BANDS:
        raise QuoteError("selected_band must be explicitly selected from low, typical, or high")
    if not isinstance(confirmed_by, str) or not confirmed_by.strip():
        raise QuoteError("confirmed_by is required")

    proposed_range = range_value(quote.get("total"))
    proposed_amount = proposed_range[selected_band]
    amount = proposed_amount if final_amount is None else number(final_amount)
    changed = amount != proposed_amount
    outside = not proposed_range["low"] <= amount <= proposed_range["high"]
    reason = override_reason.strip() if isinstance(override_reason, str) else ""
    if (changed or outside) and not reason:
        raise QuoteError("override_reason is required for a manually changed amount")

    result = deepcopy(dict(quote))
    result["selected_band"] = selected_band
    result["confirmed_by"] = confirmed_by.strip()
    result["override_reason"] = reason or None
    result["status"] = "confirmed"
    result["final_amount"] = _json_number(amount)
    result["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    result["confirmation"] = {
        "proposed_range": {band: _json_number(proposed_range[band]) for band in BANDS},
        "proposed_amount": _json_number(proposed_amount),
        "final_amount": _json_number(amount),
        "selected_band": selected_band,
        "confirmed_by": confirmed_by.strip(),
        "override_reason": reason or None,
        "confirmed_at": result["confirmed_at"],
    }
    return result
