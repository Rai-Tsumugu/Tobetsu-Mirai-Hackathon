"""P20: search approved job names and aliases without choosing a job."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize(value: str) -> str:
    """Normalize user-facing search text while preserving meaningful spaces."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _approved_aliases(job: Mapping[str, Any]) -> list[str]:
    raw_aliases = job.get("aliases", [])
    if not isinstance(raw_aliases, (list, tuple)):
        return []

    approved: list[str] = []
    for raw_alias in raw_aliases:
        if isinstance(raw_alias, Mapping):
            alias = raw_alias.get("alias")
            if not _has_text(raw_alias.get("approved_by")):
                continue
        else:
            continue
        if _has_text(alias):
            approved.append(alias.strip())
    return approved


def _is_approved_job(job: Any) -> bool:
    return isinstance(job, Mapping) and _has_text(job.get("approved_by"))


def _result(job: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "job_ref": job.get("job_ref"),
        "preset_id": job.get("preset_id"),
        "name": job.get("name"),
        "aliases": _approved_aliases(job),
        "source": job.get("source"),
        "approved_by": job.get("approved_by"),
    }


def search_jobs(jobs: Any, query: str = "") -> list[dict[str, Any]]:
    """Return every approved job whose name or approved alias contains query.

    An empty query lists all approved jobs. Results are candidates only; this
    function never selects a job or calculates/displays a price.
    """
    if not isinstance(jobs, (list, tuple)) or not isinstance(query, str):
        return []
    needle = _normalize(query)
    matches: list[dict[str, Any]] = []
    for job in jobs:
        if not _is_approved_job(job):
            continue
        name = job.get("name")
        terms = ([name] if _has_text(name) else []) + _approved_aliases(job)
        if not needle or any(needle in _normalize(term) for term in terms):
            matches.append(_result(job))
    return matches


def select_job(jobs: Any, job_id: Any) -> dict[str, Any] | None:
    """Return the approved job only when its ID identifies exactly one entry."""
    if not isinstance(jobs, (list, tuple)) or job_id is None:
        return None
    matches = [
        job for job in jobs
        if isinstance(job, Mapping) and job.get("job_id") == job_id
    ]
    return _result(matches[0]) if len(matches) == 1 and _is_approved_job(matches[0]) else None
