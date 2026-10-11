"""P12: produce a short, customer-facing quote summary for phone use."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from .common import BANDS, QuoteError, number


def customer_summary(quote: Mapping[str, Any], selected_band: str | None = None) -> dict[str, Any]:
    """Format a quote as a concise phone script without changing its source."""
    if not isinstance(quote, Mapping):
        raise QuoteError("quote must be an object")
    band = selected_band if selected_band is not None else quote.get("selected_band")
    if band is not None and band not in BANDS:
        raise QuoteError("selected_band must be low, typical, or high")

    final_amount = _confirmed_amount(quote)
    amount = final_amount if final_amount is not None else _amount(quote.get("total"), band)
    conditions = _conditions(quote)
    unresolved = any(condition["unresolved"] for condition in conditions)
    blocked = quote.get("status") in {"blocked", "unknown", "unconfirmed"} or amount is None or unresolved
    if blocked:
        amount = None
        final_amount = None
    if blocked:
        condition_note = "必要な条件・金額が未確認のため、確認後に確定します。"
    elif conditions:
        condition_note = "条件確認後に確定します。" if any(c["unresolved"] for c in conditions) else "前提条件: " + "、".join(c["text"] for c in conditions)
    else:
        condition_note = "条件確認後に確定します。" if band is None and final_amount is None else ""

    components = [] if blocked else _components(quote, band)
    fictional = _is_fictional(quote)
    if final_amount is not None:
        amount_text = f"確定額は {_yen(final_amount)} 円です。"
    elif band is None:
        amount_text = f"ご提案額は {_range_text(amount)} 円です。" if amount is not None else "金額は条件確認後にご案内します。"
    else:
        amount_text = f"{band}帯のご提案額は {_yen(amount)} 円です。" if amount is not None else "金額は条件確認後にご案内します。"

    text_parts = []
    if components:
        text_parts.append("内訳は" + "、".join(components) + "です。")
    text_parts.append(amount_text)
    if condition_note:
        text_parts.append(condition_note)
    if fictional:
        text_parts.append("金額例は架空のSimulatorデータです。")

    return {
        "quote_version": deepcopy(quote.get("quote_version")),
        "selected_band": band,
        "amount": deepcopy(amount),
        "condition_note": condition_note,
        "text": "".join(text_parts),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "fictional": fictional,
    }


def apply(quote: dict[str, Any], inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attach a generated summary snapshot to a deep-copied quote."""
    if not isinstance(quote, dict):
        raise QuoteError("quote must be an object")
    if inputs is not None and not isinstance(inputs, dict):
        raise QuoteError("inputs must be an object when provided")
    result = deepcopy(quote)
    if inputs is not None:
        result.setdefault("metadata", {}).setdefault("input_snapshot", deepcopy(inputs))
        labor = inputs.get("labor", {})
        unknowns = labor.get("unknowns", []) if isinstance(labor, Mapping) else []
        if isinstance(unknowns, list) and unknowns:
            conditions = result.setdefault("conditions", [])
            conditions.extend(
                {"text": str(value), "status": "unknown"} if isinstance(value, str)
                else {**deepcopy(value), "status": "unknown"}
                for value in unknowns
            )
    result["summary_snapshot"] = customer_summary(result)
    return result


def _confirmed_amount(quote: Mapping[str, Any]) -> Any:
    confirmation = quote.get("confirmation")
    if isinstance(confirmation, Mapping) and confirmation.get("final_amount") is not None:
        return _scalar_amount(confirmation["final_amount"])
    # Some integrations place confirmation fields on the quote itself.
    if quote.get("final_amount") is not None and quote.get("confirmed_by"):
        return _scalar_amount(quote["final_amount"])
    return None


def _scalar_amount(value: Any) -> int | float:
    parsed = number(value)
    return int(parsed) if parsed == parsed.to_integral_value() else float(parsed)


def _amount(total: Any, band: str | None) -> Any:
    if isinstance(total, Mapping):
        if any(total.get(key) is None for key in BANDS):
            return None
        parsed = {key: number(total[key]) for key in BANDS}
        if not parsed["low"] <= parsed["typical"] <= parsed["high"]:
            raise QuoteError("quote.total must satisfy low <= typical <= high")
        if band is None:
            return {key: _json_number(value) for key, value in parsed.items()}
        return _json_number(parsed[band])
    if total is None:
        return None
    return _scalar_amount(total)


def _json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _conditions(quote: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for collection in (quote.get("conditions", []), quote.get("reasons", [])):
        if not isinstance(collection, list):
            continue
        for entry in collection:
            if isinstance(entry, str) and entry.strip():
                result.append({"text": entry.strip(), "unresolved": False})
            elif isinstance(entry, Mapping):
                text = entry.get("text") or entry.get("reason") or entry.get("operation")
                if not isinstance(text, str) or not text.strip():
                    continue
                status = str(entry.get("status", "unconfirmed")).casefold()
                unresolved = status in {"blocked", "unknown", "unconfirmed", "conditional", "conditional_proposed", "pending"} or entry.get("customer_ack_status") == "pending"
                result.append({"text": text.strip(), "unresolved": unresolved})
    return result


def _components(quote: Mapping[str, Any], band: str | None) -> list[str]:
    sums = {"labor": Decimal(0), "parts": Decimal(0), "materials": Decimal(0)}
    seen = set()
    lines = quote.get("lines", [])
    if not isinstance(lines, list):
        return []
    for line in lines:
        if not isinstance(line, Mapping):
            continue
        kind = line.get("kind")
        if kind not in sums or line.get("status") in {"blocked", "unconfirmed"}:
            continue
        value = line.get("amount")
        if isinstance(value, Mapping):
            if any(value.get(key) is None for key in BANDS):
                continue
            value = value[band] if band is not None else value
        if value is None:
            continue
        try:
            if isinstance(value, Mapping):
                parsed = {key: number(value[key]) for key in BANDS}
                if not parsed["low"] <= parsed["typical"] <= parsed["high"]:
                    raise QuoteError("line amount must satisfy low <= typical <= high")
                sums[kind] += parsed["low"]
                sums[kind + "_high"] = sums.get(kind + "_high", Decimal(0)) + parsed["high"]
            else:
                sums[kind] += number(value)
                sums[kind + "_high"] = sums.get(kind + "_high", Decimal(0)) + number(value)
            seen.add(kind)
        except QuoteError:
            continue
    labels = {"labor": "工賃", "parts": "部品", "materials": "材料"}
    return [
        f"{labels[kind]} {_yen(sums[kind])}〜{_yen(sums[kind + '_high'])} 円" if band is None
        else f"{labels[kind]} {_yen(sums[kind])} 円"
        for kind in ("labor", "parts", "materials") if kind in seen
    ]


def _is_fictional(quote: Mapping[str, Any]) -> bool:
    metadata = quote.get("metadata", {})
    snapshot = metadata.get("input_snapshot", {}) if isinstance(metadata, Mapping) else {}
    values = [quote.get("source_system"), quote.get("source"), quote.get("data_mode")]
    if isinstance(snapshot, Mapping):
        values.extend((snapshot.get("source"), snapshot.get("mode")))
    for line in quote.get("lines", []) if isinstance(quote.get("lines", []), list) else []:
        if isinstance(line, Mapping):
            values.extend((line.get("source_system"), line.get("source")))
            snap = line.get("snapshot")
            if isinstance(snap, Mapping):
                values.extend((snap.get("source"), snap.get("mode")))
    return any(isinstance(value, str) and value.strip().casefold() in {"simulator", "fictional", "架空"} for value in values)


def _yen(value: Any) -> str:
    return f"{_scalar_amount(value):,}"


def _range_text(value: Mapping[str, Any]) -> str:
    return f"{_yen(value['low'])}〜{_yen(value['high'])}（典型 {_yen(value['typical'])}）"
