"""P22: prepare a safe phone question guide before quote calculation."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping

from .common import BANDS
from .p03 import validate_inputs


def _path_value(value: Any, path: str) -> Any:
    """Read a dotted object/list path, returning None when it is absent."""
    current = value
    for part in path.split(".") if path else []:
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _approval(inputs: Any) -> tuple[set[str], dict[str, Any] | None]:
    """Return paths covered by a complete, explicit conditional approval."""
    approval = inputs.get("conditional_approval") if isinstance(inputs, dict) else None
    if not isinstance(approval, dict):
        return set(), None
    approved_by = approval.get("approved_by")
    reason = approval.get("reason")
    fields = approval.get("fields")
    value_range = approval.get("range")
    if (not isinstance(approved_by, str) or not approved_by.strip()
            or not isinstance(reason, str) or not reason.strip()
            or not isinstance(fields, list) or not fields
            or any(not isinstance(path, str) or not path.strip() for path in fields)
            or len(set(fields)) != len(fields)
            or not isinstance(value_range, dict)
            or any(band not in value_range for band in BANDS)):
        return set(), None
    normalized: dict[str, float] = {}
    for band in BANDS:
        value = value_range[band]
        if isinstance(value, bool):
            return set(), None
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            return set(), None
        if not math.isfinite(parsed) or parsed < 0:
            return set(), None
        normalized[band] = parsed
    if not normalized["low"] <= normalized["typical"] <= normalized["high"]:
        return set(), None
    return set(fields), {
        "approved_by": approved_by,
        "reason": reason,
        "range": {band: value_range[band] for band in BANDS},
    }


def question_guide(
    inputs: Any, required_fields: list[str] | None = None
) -> dict[str, Any]:
    """List missing or invalid required conditions and whether calculation can proceed.

    A valid conditional approval covers only its named paths. Other unresolved
    required conditions continue to block calculation.
    """
    issues = validate_inputs(inputs)
    hard_error_paths = {issue["path"] for issue in issues if issue.get("code") != "unresolved_unknowns"}
    missing: dict[str, str] = {}
    for issue in issues:
        path = issue["path"] or "inputs"
        if path:
            missing.setdefault(path, issue["message"])

    paths = required_fields if isinstance(required_fields, (list, tuple)) else []
    for path in paths:
        if not isinstance(path, str) or not path.strip():
            continue
        value = _path_value(inputs, path)
        if value is None or value == "":
            missing.setdefault(path, "required value is missing")

    covered_paths, approval = _approval(inputs)
    questions = []
    blocked = False
    conditional = False
    for path, message in missing.items():
        is_covered = approval is not None and path in covered_paths and path not in hard_error_paths
        status = "conditional" if is_covered else "unanswered"
        conditional = conditional or is_covered
        blocked = blocked or not is_covered
        answer = _path_value(inputs, path)
        question = {
            "field": path,
            "prompt": f"{path}について確認してください。",
            "answer": deepcopy(answer),
            "status": status,
            "source_ref": path,
        }
        if is_covered:
            question["conditional_approval"] = deepcopy(approval)
        else:
            question["detail"] = message
        questions.append(question)

    status = "blocked" if blocked else ("conditional" if conditional else "ready")
    return {"questions": questions, "status": status, "can_calculate": not blocked}


def _set_path(target: Any, path: str, value: Any) -> None:
    parts = path.split(".") if isinstance(path, str) else []
    if not parts or any(not part for part in parts):
        raise ValueError("answer field must be a non-empty dotted path")
    current = target
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                current[part] = {}
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                raise ValueError(f"answer path does not exist: {path}")
            current = current[index]
        else:
            raise ValueError(f"answer path does not exist: {path}")
    leaf = parts[-1]
    if isinstance(current, dict):
        current[leaf] = deepcopy(value)
    elif isinstance(current, list) and leaf.isdigit() and int(leaf) < len(current):
        current[int(leaf)] = deepcopy(value)
    else:
        raise ValueError(f"answer path does not exist: {path}")


def answers_to_inputs(inputs: Any, answers: Mapping[str, Any]) -> Any:
    """Apply explicit dotted-path answers to a deep copy of the input."""
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be an object")
    if not isinstance(answers, Mapping):
        raise ValueError("answers must be a mapping of dotted paths to values")
    result = deepcopy(inputs)
    for path, answer in answers.items():
        _set_path(result, path, answer)
    return result
