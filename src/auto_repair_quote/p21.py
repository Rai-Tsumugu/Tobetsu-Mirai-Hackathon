"""P21: search previous quote versions for reference and reoffer safely."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping

from .p15 import revise_quote


_HISTORY_NOTICE = (
    "過去見積りの金額です。現在額として使用せず、今回の条件で再計算してください。"
)


def search_quotes(
    store: Any,
    customer_ref: str | None = None,
    vehicle_ref: str | None = None,
    job_ref: str | None = None,
) -> list[dict[str, Any]]:
    """Return matching historical quote versions as reference-only copies."""
    quotes = store.list_quotes(
        customer_ref=customer_ref,
        vehicle_ref=vehicle_ref,
        job_ref=job_ref,
    )
    results = deepcopy(quotes)
    for quote in results:
        quote["reference_only"] = True
        quote["history_notice"] = _HISTORY_NOTICE
        snapshot = quote.get("metadata", {}).get("input_snapshot", {})
        quote["amount_snapshot"] = deepcopy(quote.get("total"))
        quote["condition_snapshot"] = deepcopy(quote.get("conditions", snapshot.get("conditions", [])))
        quote["price_dates"] = {
            "labor_rate": snapshot.get("labor_rate", {}).get("effective_from"),
            "items": [{"item_id":item.get("item_id"),"updated_at":item.get("updated_at")}
                      for item in snapshot.get("items", [])],
        }
    return results


def reoffer_quote(
    store: Any,
    quote_id: str,
    quote_version: int,
    current_inputs: Mapping[str, Any],
    calculate: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]:
    """Recalculate a historical quote as a new, unsaved proposal version."""
    return revise_quote(
        store,
        quote_id,
        quote_version,
        current_inputs,
        calculate,
    )
