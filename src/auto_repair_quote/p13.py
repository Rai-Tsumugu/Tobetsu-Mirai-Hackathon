"""P13: guide quote drafts through the required estimate steps."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from . import p03
from .common import BANDS, QuoteError, range_value

_LABELS = ("vehicle", "job", "conditions", "amount", "confirm")


def _step_index(step: Any) -> int:
    if isinstance(step, bool) or not isinstance(step, int) or not 0 <= step < len(_LABELS):
        raise QuoteError("step must be an integer from 0 through 4")
    return step


def validate_step(inputs: Any, step: int, quote: Any = None) -> list[dict[str, str]]:
    """Return missing/invalid requirements for one step without changing inputs."""
    index = _step_index(step)
    if not isinstance(inputs, Mapping):
        return [_issue("invalid_inputs", "inputs", "inputs must be an object")]
    issues: list[dict[str, str]] = []

    if index == 0:
        _required_ref(inputs, "vehicle_ref", issues)
    elif index == 1:
        _required_ref(inputs, "job_ref", issues)
    elif index == 2:
        issues.extend(p03.validate_inputs(dict(inputs)))
    elif index == 3:
        total = quote.get("total") if isinstance(quote, Mapping) else None
        try:
            range_value(total)
        except QuoteError as error:
            issues.append(_issue("invalid_proposed_amount", "quote.total", str(error)))
    else:
        issues.extend(validate_step(inputs, 3, quote))
        if isinstance(quote, Mapping) and quote.get("status") in {"blocked", "unknown", "pending"}:
            issues.append(_issue("unavailable_quote", "quote.status", "quote cannot be confirmed"))
        selected_band = quote.get("selected_band") if isinstance(quote, Mapping) else None
        confirmed_by = quote.get("confirmed_by") if isinstance(quote, Mapping) else None
        if selected_band not in BANDS:
            issues.append(_issue("missing_selected_band", "quote.selected_band", "a valid selected band is required"))
        if not _nonempty(confirmed_by):
            issues.append(_issue("missing_confirmed_by", "quote.confirmed_by", "confirmed_by is required"))
    return issues


def advance_step(draft: Any, quote: Any = None) -> dict[str, Any]:
    """Return a copied draft advanced by one step after its current gate passes."""
    if not isinstance(draft, Mapping):
        raise QuoteError("draft must be an object")
    step = _step_index(draft.get("step"))
    inputs = draft.get("inputs")
    issues = validate_step(inputs, step, quote)
    if issues:
        raise QuoteError(f"step {step} is incomplete: {issues[0]['code']} at {issues[0]['path']}")
    if step == len(_LABELS) - 1:
        raise QuoteError("confirm is the final step")
    result = deepcopy(dict(draft))
    result["step"] = step + 1
    return result


def form_state(inputs: Any, step: int = 0, quote: Any = None) -> dict[str, Any]:
    """Build the minimal UI state for a single form step."""
    index = _step_index(step)
    issues = validate_step(inputs, index, quote)
    return {"step": index, "label": _LABELS[index], "issues": issues, "can_advance": not issues}


def _required_ref(inputs: Mapping[str, Any], field: str, issues: list[dict[str, str]]) -> None:
    if not _nonempty(inputs.get(field)):
        issues.append(_issue(f"missing_{field}", field, f"{field} is required"))


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
