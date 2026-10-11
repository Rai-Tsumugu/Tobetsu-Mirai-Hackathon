"""P26: compare two immutable versions of the same quote."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .common import BANDS, QuoteError


def compare_versions(from_quote: Mapping[str, Any], to_quote: Mapping[str, Any]) -> dict[str, Any]:
    """Describe line, amount, and condition changes between quote snapshots."""
    if not isinstance(from_quote, Mapping) or not isinstance(to_quote, Mapping):
        raise QuoteError("quotes must be objects")
    quote_id = from_quote.get("quote_id")
    if not quote_id or quote_id != to_quote.get("quote_id"):
        raise QuoteError("quotes must have the same quote_id")
    from_version = from_quote.get("quote_version")
    to_version = to_quote.get("quote_version")
    old_lines = _list(from_quote, "lines")
    new_lines = _list(to_quote, "lines")

    old_ids = _unique_ids(old_lines, "line_id", "from_quote.lines")
    new_ids = _unique_ids(new_lines, "line_id", "to_quote.lines")
    matched: list[tuple[int, int]] = []
    used_old: set[int] = set()
    used_new: set[int] = set()
    for line_id in old_ids.keys() & new_ids.keys():
        oi, ni = old_ids[line_id], new_ids[line_id]
        matched.append((oi, ni))
        used_old.add(oi)
        used_new.add(ni)

    warnings: list[str] = []
    old_refs = _ref_indexes(old_lines, used_old)
    new_refs = _ref_indexes(new_lines, used_new)
    for ref in old_refs.keys() & new_refs.keys():
        oi_list, ni_list = old_refs[ref], new_refs[ref]
        if len(oi_list) == len(ni_list) == 1:
            oi, ni = oi_list[0], ni_list[0]
            matched.append((oi, ni))
            used_old.add(oi)
            used_new.add(ni)
        else:
            warnings.append(f"ambiguous source_ref {ref!r}; lines were left unmatched")

    added = [deepcopy(dict(line)) for i, line in enumerate(new_lines) if i not in used_new]
    removed = [deepcopy(dict(line)) for i, line in enumerate(old_lines) if i not in used_old]
    changed = []
    for oi, ni in matched:
        before, after = old_lines[oi], new_lines[ni]
        if dict(before) != dict(after):
            changed.append({"from": deepcopy(dict(before)), "to": deepcopy(dict(after))})

    return {
        "quote_id": deepcopy(quote_id),
        "from_version": deepcopy(from_version),
        "to_version": deepcopy(to_version),
        "added": added,
        "removed": removed,
        "changed": changed,
        "amount_delta": _amount_delta(from_quote, to_quote),
        "condition_delta": _condition_delta(_list(from_quote, "conditions"), _list(to_quote, "conditions")),
        "warnings": warnings,
    }


def _list(quote: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = quote.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise QuoteError(f"quote.{key} must be a list of objects")
    return value


def _unique_ids(lines: list[Mapping[str, Any]], key: str, path: str) -> dict[Any, int]:
    indexes: dict[Any, int] = {}
    for i, line in enumerate(lines):
        value = line.get(key)
        if value is None:
            continue
        try:
            duplicate = value in indexes
        except TypeError:
            raise QuoteError(f"{path}.{key} must be scalar") from None
        if duplicate:
            raise QuoteError(f"{path} contains duplicate {key}")
        indexes[value] = i
    return indexes


def _ref_indexes(lines: list[Mapping[str, Any]], excluded: set[int]) -> dict[Any, list[int]]:
    result: dict[Any, list[int]] = {}
    for i, line in enumerate(lines):
        ref = line.get("source_ref")
        if i not in excluded and ref is not None:
            result.setdefault(ref, []).append(i)
    return result


def _amount_delta(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, int | float | None]:
    old_total, new_total = old.get("total"), new.get("total")
    if not isinstance(old_total, Mapping) or not isinstance(new_total, Mapping):
        raise QuoteError("quote.total must be an object")
    result = {}
    for band in BANDS:
        before = _amount(old_total.get(band), f"from_quote.total.{band}")
        after = _amount(new_total.get(band), f"to_quote.total.{band}")
        delta = None if before is None or after is None else after - before
        result[band] = _json_number(delta) if delta is not None else None
    return result


def _amount(value: Any, path: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise QuoteError(f"{path} must be a finite non-negative amount or null")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise QuoteError(f"{path} must be a finite non-negative amount or null") from None
    if not parsed.is_finite() or parsed < 0:
        raise QuoteError(f"{path} must be a finite non-negative amount or null")
    return parsed


def _condition_delta(old: list[Mapping[str, Any]], new: list[Mapping[str, Any]]) -> dict[str, Any]:
    old_index = _condition_index(old, "from_quote.conditions")
    new_index = _condition_index(new, "to_quote.conditions")
    added, removed, changed = [], [], []
    for key, condition in new_index.items():
        if key not in old_index:
            added.append(deepcopy(dict(condition)))
        elif dict(old_index[key]) != dict(condition):
            changed.append({"from": deepcopy(dict(old_index[key])), "to": deepcopy(dict(condition))})
    for key, condition in old_index.items():
        if key not in new_index:
            removed.append(deepcopy(dict(condition)))
    return {"added": added, "removed": removed, "changed": changed}


def _condition_index(conditions: list[Mapping[str, Any]], path: str) -> dict[tuple[str, Any], Mapping[str, Any]]:
    result = {}
    for i, condition in enumerate(conditions):
        key = next(((field, condition[field]) for field in ("condition_ref", "source_ref", "id") if condition.get(field) is not None), ("value", repr(sorted(condition.items()))))
        try:
            exists = key in result
        except TypeError:
            raise QuoteError(f"{path} identity must be scalar") from None
        if exists:
            raise QuoteError(f"{path} contains duplicate condition identity")
        result[key] = condition
    return result


def _json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)
