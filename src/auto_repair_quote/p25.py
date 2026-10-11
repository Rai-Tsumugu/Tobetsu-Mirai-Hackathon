"""P25: combine quote lines and surface explicitly approved shared items."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from .common import BANDS, QuoteError, _json_number


def combine_quotes(
    quotes: Iterable[Mapping[str, Any]],
    accepted_dedup_refs: Iterable[str] | None = None,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Aggregate quote rows without mutating source quotes.

    Deduplication is limited to parts/materials with equal snapshot item_id and
    usage_ref. The selected ref names the row to omit from the combined sum.
    """
    if isinstance(quotes, (str, bytes, Mapping)):
        raise QuoteError("quotes must be an iterable of quote objects")
    try:
        quote_rows = list(quotes)
    except TypeError:
        raise QuoteError("quotes must be an iterable of quote objects") from None

    candidates: dict[tuple[str, str], list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    job_refs: list[Any] = []
    seen_refs: set[str] = set()
    for qi, quote in enumerate(quote_rows):
        if not isinstance(quote, Mapping):
            raise QuoteError(f"quotes.{qi} must be an object")
        quote_id, version = quote.get("quote_id"), quote.get("quote_version")
        if quote_id is None or version is None:
            raise QuoteError(f"quotes.{qi} requires quote_id and quote_version")
        job_ref = quote.get("job_ref", quote.get("job_id", quote_id))
        job_refs.append(deepcopy(job_ref))
        lines = quote.get("lines")
        if not isinstance(lines, list):
            raise QuoteError(f"quotes.{qi}.lines must be a list")
        for li, line in enumerate(lines):
            if not isinstance(line, Mapping):
                raise QuoteError(f"quotes.{qi}.lines.{li} must be an object")
            line_id = line.get("line_id")
            if line_id is None or not str(line_id).strip():
                raise QuoteError(f"quotes.{qi}.lines.{li}.line_id is required")
            ref = f"{quote_id}:{version}:{line_id}"
            if ref in seen_refs:
                raise QuoteError(f"duplicate line ref: {ref}")
            seen_refs.add(ref)
            row = deepcopy(dict(line))
            row["line_id"] = ref
            row["source_line_id"] = str(line_id)
            row["quote_id"] = str(quote_id)
            row["quote_version"] = str(version)
            row["line_ref"] = ref
            rows.append(row)
            if line.get("kind") not in {"parts", "materials"}:
                continue
            snapshot = line.get("snapshot")
            if not isinstance(snapshot, Mapping):
                continue
            item_id, usage_ref = snapshot.get("item_id"), snapshot.get("usage_ref")
            if item_id in (None, "") or usage_ref in (None, ""):
                continue
            key = (str(item_id), str(usage_ref))
            candidates.setdefault(key, []).append({"ref": ref, "line": line})

    candidate_groups = []
    eligible_refs: set[str] = set()
    for (item_id, usage_ref), members in candidates.items():
        if len(members) < 2:
            continue
        refs = [member["ref"] for member in members]
        eligible_refs.update(refs)
        differences = []
        baseline = members[0]["line"]
        for member in members[1:]:
            line = member["line"]
            diff = {}
            for field in ("quantity_range", "unit", "amount"):
                if line.get(field) != baseline.get(field):
                    diff[field] = {"baseline": deepcopy(baseline.get(field)), "candidate": deepcopy(line.get(field))}
            differences.append({"ref": member["ref"], "differences": diff})
        candidate_groups.append({"item_id": item_id, "usage_ref": usage_ref, "refs": refs, "differences": differences})

    if accepted_dedup_refs is None:
        accepted = []
    elif isinstance(accepted_dedup_refs, (str, bytes)):
        raise QuoteError("accepted_dedup_refs must be an iterable of refs")
    else:
        try:
            accepted = list(accepted_dedup_refs)
        except TypeError:
            raise QuoteError("accepted_dedup_refs must be an iterable of refs") from None
    if any(not isinstance(ref, str) or not ref.strip() for ref in accepted):
        raise QuoteError("accepted dedup refs must be non-empty strings")
    if len(set(accepted)) != len(accepted):
        raise QuoteError("accepted dedup refs must be unique")
    if any(ref not in eligible_refs for ref in accepted):
        raise QuoteError("accepted dedup ref must belong to a shared parts/materials candidate")
    if accepted and (not isinstance(approved_by, str) or not approved_by.strip()):
        raise QuoteError("approved_by is required when dedup refs are accepted")

    removed = set(accepted)
    included = [row for row in rows if row["line_ref"] not in removed]
    return {
        "job_refs": job_refs,
        "lines": included,
        "shared_item_candidates": candidate_groups,
        "accepted_dedup_refs": accepted,
        "approved_by": approved_by.strip() if accepted else None,
        "subtotal": _sum_rows(included),
        "original_subtotal": _sum_rows(rows),
        "delta": _subtract_ranges(_sum_rows(included), _sum_rows(rows)),
    }


def _sum_rows(rows: list[Mapping[str, Any]]) -> dict[str, int | float | None]:
    totals = {band: Decimal(0) for band in BANDS}
    unknown = {band: False for band in BANDS}
    for i, row in enumerate(rows):
        amount = row.get("amount")
        if isinstance(amount, Mapping):
            if set(amount) != set(BANDS):
                raise QuoteError(f"line {row.get('line_ref')} amount must contain all bands")
            values = {band: amount[band] for band in BANDS}
        elif amount is None:
            values = {band: None for band in BANDS}
        else:
            values = {band: amount for band in BANDS}
        for band, value in values.items():
            if value is None:
                unknown[band] = True
                continue
            if isinstance(value, bool):
                raise QuoteError(f"line {row.get('line_ref')} amount.{band} must be finite")
            try:
                parsed = Decimal(str(value))
            except (InvalidOperation, ValueError, TypeError):
                raise QuoteError(f"line {row.get('line_ref')} amount.{band} must be finite") from None
            if not parsed.is_finite():
                raise QuoteError(f"line {row.get('line_ref')} amount.{band} must be finite")
            totals[band] += parsed
    return {band: None if unknown[band] else _json_number(totals[band]) for band in BANDS}


def _subtract_ranges(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, int | float | None]:
    return {band: None if left[band] is None or right[band] is None else _json_number(Decimal(str(left[band])) - Decimal(str(right[band]))) for band in BANDS}
