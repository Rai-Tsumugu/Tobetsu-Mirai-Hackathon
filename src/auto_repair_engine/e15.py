"""E15: manual voice-note candidates that need a human before changing observations.

The simulator accepts a typed transcription only. It never records the input text
or raw audio and only exposes allowlisted tags in candidate results and traces.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .contract import reference_labor

ENGINE_ID = "e15_voice_candidate_confirmation"
RULE_VERSION = "e15-voice-candidate-confirmation-v1"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。音声認識・実測工数・実価格・実車検証は行いません。"
_ALLOWED_FIELDS = {"rust_observation", "rotor_relevance", "snow_observation"}
_ALLOWED_TAGS = {
    "rust_present": ("rust_observation", "present"),
    "rust_absent": ("rust_observation", "absent"),
    "rotor_seized": ("rotor_relevance", "relevant"),
    "rotor_not_seized": ("rotor_relevance", "unrelated"),
    "snow_present": ("snow_observation", "present"),
    "snow_absent": ("snow_observation", "absent"),
}
_NULL_RANGE = {"low": None, "typical": None, "high": None}


def _candidate(candidate_id: str, tag: str, status: str, field: str | None = None,
               value: Any = None, side: str | None = None,
               alternatives: list[str] | None = None,
               ambiguity: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"candidate_id": candidate_id, "tag": tag, "status": status}
    if field is not None:
        result["field"] = field
        result["value"] = value
    if side is not None:
        result["side"] = side
    if alternatives:
        result["alternatives"] = list(alternatives)
    if ambiguity is not None:
        result["ambiguity"] = ambiguity
    return result


def _has_negation(text: str, start: int, end: int, kind: str) -> bool:
    """Recognize negation attached to this condition keyword, within its local clause."""
    before = text[max(0, start - 16):start]
    after = text[end:min(len(text), end + 16)]
    # Clause punctuation stops a prior negative from affecting a later condition.
    before = re.split(r"[。.!！?？,、;；]", before)[-1]
    after = re.split(r"[。.!！?？,、;；]", after)[0]
    particle = r"(?:は|が|も)?"
    endings = r"(?:ない|なく|無し|なし|ありません|ではない|じゃない|ではなく|じゃなく|見られない|見られず|出てない|出ていない|ていない|てない|てません|してない|していない|してません|ず)"
    if re.search(particle + endings, after):
        return True
    # Also accept forms such as 「錆はありません」 where the particle follows the keyword.
    if re.search(particle + endings + r"\s*$", after):
        return True
    # Negation may immediately precede a condition in forms like 「錆ではなく塗装」.
    target_names = {"rust": r"(?:錆|さび|サビ)", "rotor": r"(?:固着|固ま)", "snow": r"(?:雪|氷|凍結)"}[kind]
    return bool(re.search(r"(?:ではなく|じゃなく|ではない|じゃない|なく|なし|無し)\s*$", before)
                and re.search(target_names + r"\s*$", before))


def extract_candidates(manual_transcription: str) -> dict[str, Any]:
    """Extract allowlisted condition tags from typed text, without returning the text."""
    if not isinstance(manual_transcription, str):
        return {"candidates": [], "unknowns": ["manual_transcription:string_required"]}
    if len(manual_transcription) > 2000:
        return {"candidates": [], "unknowns": ["manual_transcription:too_long"]}
    text = manual_transcription
    patterns = [
        ("rust", r"錆|さび|サビ", "rust_present", "rust_absent"),
        ("rotor", r"ローター.{0,8}固着|固着", "rotor_seized", "rotor_not_seized"),
        ("snow", r"雪|氷|凍結", "snow_present", "snow_absent"),
    ]
    detections: list[dict[str, Any]] = []
    for kind, pattern, positive_tag, negative_tag in patterns:
        for match in re.finditer(pattern, text):
            tag = negative_tag if _has_negation(text, match.start(), match.end(), kind) else positive_tag
            clause_start = max([text.rfind(mark, 0, match.start()) + 1 for mark in "。.!！?？,、;；\n"])
            clause_end_candidates = [text.find(mark, match.end()) for mark in "。.!！?？,、;；\n"]
            clause_end = min((position for position in clause_end_candidates if position >= 0), default=len(text))
            clause = text[clause_start:clause_end]
            left = bool(re.search(r"左(?:側|輪|前|後)?", clause))
            right = bool(re.search(r"右(?:側|輪|前|後)?", clause))
            uncertain = bool(re.search(r"(?:左か右|右か左|左右どちら|左右どっち|どちらか)", clause))
            both = bool(re.search(r"(?:左右|両側|両方)", clause))
            if uncertain or (left and right and not both):
                detections.append({"kind": kind, "tag": tag, "side": None, "ambiguous_side": True, "start": match.start()})
            elif both:
                detections.extend({"kind": kind, "tag": tag, "side": side, "ambiguous_side": False, "start": match.start()}
                                  for side in ("left", "right"))
            else:
                side = "left" if left else ("right" if right else None)
                detections.append({"kind": kind, "tag": tag, "side": side, "ambiguous_side": False, "start": match.start()})

    # Keep separate left/right facts. Conflicting values for the same condition
    # and side remain unresolved until a person explicitly chooses one.
    grouped: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    for item in sorted(detections, key=lambda value: value["start"]):
        grouped.setdefault((item["kind"], item["side"]), []).append(item)
    candidates: list[dict[str, Any]] = []
    for (kind, side), items in grouped.items():
        tags = list(dict.fromkeys(item["tag"] for item in items))
        ambiguous_side = any(item["ambiguous_side"] for item in items)
        if len(tags) > 1:
            field = _ALLOWED_TAGS[tags[0]][0]
            candidates.append(_candidate(f"voice-{len(candidates) + 1}", tags[0], "ambiguous", field,
                                         _ALLOWED_TAGS[tags[0]][1], side=side, alternatives=tags,
                                         ambiguity="condition_conflict"))
        else:
            tag = tags[0]
            field, value = _ALLOWED_TAGS[tag]
            if ambiguous_side:
                candidates.append(_candidate(f"voice-{len(candidates) + 1}", tag, "ambiguous", field,
                                             value, alternatives=["left", "right"], ambiguity="side"))
            else:
                candidates.append(_candidate(f"voice-{len(candidates) + 1}", tag, "pending", field, value, side))
    unknowns = [] if candidates else (["manual_transcription:no_allowed_tags"] if text.strip() else [])
    return {"candidates": candidates, "unknowns": unknowns}


def _safe_candidate(candidate: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(candidate, dict):
        return None, "candidate:object_required"
    tag = candidate.get("tag")
    status = candidate.get("status")
    if status == "ambiguous":
        alternatives = candidate.get("alternatives")
        tag = candidate.get("tag")
        ambiguity = candidate.get("ambiguity", "side")
        candidate_id = candidate.get("candidate_id")
        if ambiguity == "condition_conflict":
            valid = (isinstance(alternatives, list) and len(alternatives) == 2
                     and all(option in _ALLOWED_TAGS for option in alternatives)
                     and _ALLOWED_TAGS[alternatives[0]][0] == _ALLOWED_TAGS[alternatives[1]][0]
                     and _ALLOWED_TAGS[alternatives[0]][1] != _ALLOWED_TAGS[alternatives[1]][1]
                     and tag in alternatives
                     and candidate.get("field") == _ALLOWED_TAGS[alternatives[0]][0]
                     and candidate.get("value") == _ALLOWED_TAGS[tag][1]
                     and candidate.get("side") in (None, "left", "right"))
        else:
            valid = (tag in _ALLOWED_TAGS and isinstance(alternatives, list)
                     and alternatives == ["left", "right"] and ambiguity == "side")
        if not valid:
            return None, "candidate:invalid_alternatives"
        if candidate_id is not None and (not isinstance(candidate_id, str) or not re.fullmatch(r"voice-\d+", candidate_id)):
            return None, "candidate:invalid_id"
        return {"candidate_id": candidate_id, "status": status,
                "tag": tag, "field": candidate.get("field", _ALLOWED_TAGS[tag][0] if tag in _ALLOWED_TAGS else None),
                "value": _ALLOWED_TAGS[tag][1] if tag in _ALLOWED_TAGS else None,
                "alternatives": list(alternatives), "ambiguity": ambiguity,
                "side": candidate.get("side")}, None
    if tag not in _ALLOWED_TAGS:
        return None, "candidate:unknown_tag"
    field, value = _ALLOWED_TAGS[tag]
    if status != "pending" or candidate.get("field") != field or candidate.get("value") != value:
        return None, "candidate:invalid_or_already_resolved"
    side = candidate.get("side")
    if side not in (None, "left", "right"):
        return None, "candidate:invalid_side"
    candidate_id = candidate.get("candidate_id")
    if candidate_id is not None and (not isinstance(candidate_id, str) or not re.fullmatch(r"voice-\d+", candidate_id)):
        return None, "candidate:invalid_id"
    return {"candidate_id": candidate_id, "tag": tag, "status": status,
            "field": field, "value": value, "side": side}, None


def confirm_candidate(scenario_input: dict[str, Any], candidate: dict[str, Any], actor: str,
                      reason: str, approved: bool = True, resolved_side: str | None = None,
                      resolved_tag: str | None = None) -> dict[str, Any]:
    """Append an audited observation; never mutate the supplied scenario or overwrite history."""
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else None
    safe, error = _safe_candidate(candidate)
    if scenario is None:
        error = "scenario_input:object_required"
    if error:
        return {"scenario_input": scenario, "approval": None, "error": error}
    if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
        return {"scenario_input": scenario, "approval": None, "error": "confirmation:actor_and_reason_required"}
    if not isinstance(approved, bool):
        return {"scenario_input": scenario, "approval": None, "error": "confirmation:approved_boolean_required"}

    tag = safe.get("tag")
    if safe["status"] == "ambiguous":
        if safe.get("ambiguity") == "condition_conflict":
            if resolved_tag not in safe["alternatives"]:
                return {"scenario_input": scenario, "approval": None, "error": "confirmation:ambiguous_candidate_requires_allowed_resolution"}
            tag = resolved_tag
        elif resolved_side not in safe["alternatives"]:
            return {"scenario_input": scenario, "approval": None, "error": "confirmation:ambiguous_candidate_requires_allowed_resolution"}
    elif resolved_side is not None or resolved_tag is not None:
        return {"scenario_input": scenario, "approval": None, "error": "confirmation:resolution_only_for_ambiguous_candidate"}
    if not approved:
        approval = {"candidate_id": safe.get("candidate_id"), "tag": tag, "actor": actor.strip(),
                    "reason": reason.strip(), "approved": False}
        return {"scenario_input": scenario, "approval": approval, "error": None}

    field, value = _ALLOWED_TAGS[tag]
    side = (resolved_side if safe.get("ambiguity") == "side" else safe.get("side"))
    if not isinstance(scenario.get("fields"), dict):
        return {"scenario_input": deepcopy(scenario_input), "approval": None, "error": "scenario_input:fields_must_be_object"}
    if "observations" in scenario and not isinstance(scenario["observations"], list):
        return {"scenario_input": deepcopy(scenario_input), "approval": None,
                "error": "scenario_input:observations_must_be_list"}
    fields = scenario["fields"]
    previous = fields.get(field)
    old_value = previous.get("value") if isinstance(previous, dict) else previous
    observation = {"field": field, "value": value, "status": "confirmed", "source": "e15_manual_voice",
                   "actor": actor.strip(), "reason": reason.strip(), "approved": True,
                   "candidate_id": safe.get("candidate_id")}
    if side:
        observation["side"] = side
    observations = scenario.setdefault("observations", [])
    observations.append(deepcopy(observation))
    # A one-state business field cannot safely represent two opposite sides.
    # Keep explicit side observations separately; only an unresolved-side
    # candidate that a human resolves may update the shared field projection.
    if safe.get("ambiguity") == "side" or side is None:
        fields[field] = {"value": value, "status": "confirmed", "source": "e15_manual_voice", "confirmed_at": None}
    else:
        by_field = scenario.setdefault("side_observations", {})
        if not isinstance(by_field, dict):
            return {"scenario_input": deepcopy(scenario_input), "approval": None,
                    "error": "scenario_input:side_observations_must_be_object"}
        per_side = by_field.setdefault(field, {})
        if not isinstance(per_side, dict):
            return {"scenario_input": deepcopy(scenario_input), "approval": None,
                    "error": "scenario_input:side_observations_field_must_be_object"}
        per_side[side] = {"value": value, "status": "confirmed", "source": "e15_manual_voice",
                          "actor": actor.strip(), "reason": reason.strip(), "candidate_id": safe.get("candidate_id")}
    approval = {"candidate_id": safe.get("candidate_id"), "tag": tag, "field": field,
                "actor": actor.strip(), "reason": reason.strip(), "approved": True,
                "old_value": old_value, "new_value": value}
    if side:
        approval["side"] = side
    return {"scenario_input": scenario, "approval": approval, "error": None}


def _null_labor(unknowns: list[str]) -> dict[str, Any]:
    return {"person_hours": dict(_NULL_RANGE), "elapsed_hours": dict(_NULL_RANGE),
            "breakdown": [], "unknowns": list(dict.fromkeys(unknowns))}


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    """Run the common simulator calculation while keeping voice candidates pending."""
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else None
    version = scenario.get("rule_version") or RULE_VERSION
    candidates: list[dict[str, Any]] = []
    issues: list[str] = []
    if not isinstance(scenario_input, dict):
        issues.append("scenario_input:object_required")
    if rule_pack is not None:
        if pack is None:
            issues.append("rule_pack:object_required")
        else:
            allowed = {"engine_id", "rule_version", "manual_transcription"}
            if set(pack) - allowed:
                issues.append("rule_pack:unknown_key")
            if pack.get("engine_id") not in (None, ENGINE_ID, "e15"):
                issues.append("rule_pack:engine_id_mismatch")
            if "rule_version" in pack and (not isinstance(pack["rule_version"], str) or not pack["rule_version"].strip()):
                issues.append("rule_pack:rule_version_required")
            if pack.get("rule_version") and scenario.get("rule_version") and pack["rule_version"] != scenario["rule_version"]:
                issues.append("rule_pack:pinned_version_mismatch")
            version = pack.get("rule_version") or version
            if "manual_transcription" in pack:
                extracted = extract_candidates(pack["manual_transcription"])
                candidates = extracted["candidates"]
                issues.extend(extracted["unknowns"])
    if not isinstance(version, str) or not version.strip():
        issues.append("rule_version:required")
    if issues and any(not item.endswith(":no_allowed_tags") for item in issues):
        labor = _null_labor(issues)
        status = "missing-required"
        trace = [{"event": "voice_candidates_checked", "tags": [item["tag"] for item in candidates],
                  "statuses": [item["status"] for item in candidates], "raw_transcription_stored": False}]
    else:
        labor, _, _ = reference_labor(scenario)
        labor = deepcopy(labor)
        blocking = [item for item in labor.get("unknowns", []) if not item.endswith(":elapsed_duration_unknown")]
        status = "missing-required" if blocking else ("partial" if labor.get("unknowns") else "proposed")
        trace = [{"event": "voice_candidates_checked", "tags": [item["tag"] for item in candidates],
                  "statuses": [item["status"] for item in candidates], "raw_transcription_stored": False},
                 {"event": "labor_calculated", "rule_version": version, "operation_keys": [
                     row.get("operation_id") for row in labor.get("breakdown", []) if row.get("operation_id")]}]
    approvals = []
    for item in scenario.get("observations", []) if isinstance(scenario.get("observations"), list) else []:
        if isinstance(item, dict) and item.get("source") == "e15_manual_voice":
            approvals.append({key: item.get(key) for key in ("candidate_id", "field", "value", "actor", "reason")})
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": status, "labor": labor,
            "trace": trace, "operation_keys": [row.get("operation_id") for row in labor.get("breakdown", [])
                                                 if row.get("operation_id")],
            "approvals": approvals, "simulator_notice": SIMULATOR_NOTICE,
            "voice_candidates": candidates}
