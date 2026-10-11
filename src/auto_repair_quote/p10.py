"""P10: attach provenance badges without changing quote amounts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .common import QuoteError


def source_badges(quote: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build one provenance badge per quote line from its stored snapshot."""
    if not isinstance(quote, Mapping):
        raise QuoteError("quote must be an object")
    lines = quote.get("lines", [])
    if not isinstance(lines, list):
        raise QuoteError("quote.lines must be a list")

    badges = []
    for index, line in enumerate(lines):
        if not isinstance(line, Mapping):
            raise QuoteError(f"quote.lines.{index} must be an object")
        snapshot = line.get("snapshot")
        snapshot = snapshot if isinstance(snapshot, Mapping) else {}
        source_system = line.get("source_system")
        source_ref = line.get("source_ref")
        updated_at = None
        price_type = None
        fictional = _is_simulator(source_system)
        label = "出所未確認"
        status = "unconfirmed"

        if line.get("kind") == "labor":
            rate = snapshot.get("labor_rate")
            rate = rate if isinstance(rate, Mapping) else {}
            basis = rate.get("basis")
            basis = basis if isinstance(basis, list) else []
            effective_from = rate.get("effective_from")
            updated_at = effective_from if _nonempty(effective_from) else None
            price_type = "工賃"
            has_basis = any(
                isinstance(entry, Mapping)
                and _nonempty(entry.get("label"))
                and entry.get("value") is not None
                for entry in basis
            )
            fictional = fictional or any(
                isinstance(entry, Mapping) and "架空" in str(entry.get("label", ""))
                for entry in basis
            )
            if has_basis and updated_at:
                label = "架空の工賃設定" if fictional else "工賃設定"
                status = "fictional" if fictional else "available"
            else:
                label = "工賃根拠・適用日未確認"
        else:
            # P04 item lines keep source/date/type directly in their snapshot.
            price_type = snapshot.get("price_type")
            updated_at = snapshot.get("updated_at")
            item_source = snapshot.get("source")
            if item_source:
                source_system = item_source
            fictional = fictional or _is_simulator(item_source)
            source_ref = snapshot.get("item_id", source_ref)
            contract_unclear = _contract_source(source_system, item_source, snapshot)
            if contract_unclear:
                label = "契約条件未確認"
                status = "contract_unconfirmed"
            elif _nonempty(source_system) and _nonempty(source_ref) and _nonempty(updated_at) and price_type:
                label = "架空データ（Simulator）" if fictional else "価格根拠あり"
                status = "fictional" if fictional else "available"
            else:
                label = "価格の出所・取得日未確認"
                status = "unconfirmed"

        badges.append({
            "line_id": deepcopy(line.get("line_id")),
            "source_system": deepcopy(source_system),
            "source_ref": deepcopy(source_ref),
            "updated_at": deepcopy(updated_at),
            "price_type": deepcopy(price_type),
            "fictional": fictional,
            "label": label,
            "status": status,
        })
    return badges


def apply(quote: dict[str, Any], inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a deep copy with provenance badges; amounts are left untouched."""
    if not isinstance(quote, dict):
        raise QuoteError("quote must be an object")
    if inputs is not None and not isinstance(inputs, dict):
        raise QuoteError("inputs must be an object when provided")
    result = deepcopy(quote)
    result["source_badges"] = source_badges(result)
    return result


def _is_simulator(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() in {"simulator", "fictional", "架空"}


def _contract_source(system: Any, source: Any, snapshot: Mapping[str, Any]) -> bool:
    """External contract provenance remains explicitly unconfirmed absent evidence."""
    text = " ".join(str(value).casefold() for value in (system, source) if value is not None)
    if any(token in text for token in ("contract", "契約", "external", "外部")):
        # No contract-checked flag is part of the agreed input shape. Never infer
        # permission or terms from the mere presence of an external reference.
        return snapshot.get("contract_terms_confirmed") is not True
    return False


def _nonempty(value: Any) -> bool:
    return value is not None and isinstance(value, (str, int)) and not isinstance(value, bool) and bool(str(value).strip())
