"""E13: schema-driven condition intake for the fictional repair simulator."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from . import e07

ENGINE_ID = "e13_schema_driven_condition_form"
RULE_VERSION = "e13-schema-driven-condition-form-v1"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_NULL = {"low": None, "typical": None, "high": None}

# Values are fictional UI choices. Operation ids connect observations to the
# calculation rows; no regional or age-based multiplier is implied.
FORM_SCHEMAS: dict[str, list[dict[str, Any]]] = {
    "front_brake_service": [
        {"field": "work_scope", "label": "作業範囲", "choices": ["front_brake_service"], "required": True, "operation_ids": ["base_service"]},
        {"field": "included_operations", "label": "基準に含まれる作業", "choices": ["remove_install", "rust_observation", "snow_removal"], "multiple": True, "required": True, "operation_ids": ["base_service", "included_carry", "replacement_carry", "snow_melt"]},
        {"field": "rotor_relevance", "label": "ローター固着の関連", "choices": ["relevant", "unrelated"], "required": True, "operation_ids": ["rotor_seizure"]},
        {"field": "rotor_seizure_hours", "label": "固着対応の条件幅（人時）", "kind": "range", "required_if": {"field": "rotor_relevance", "equals": "relevant"}, "operation_ids": ["rotor_seizure"]},
        {"field": "subframe_relevance", "label": "サブフレーム作業の関連", "choices": ["relevant", "unrelated", "unknown"], "required": True, "operation_ids": ["base_service"]},
        {"field": "parts_wait_stock_checked", "label": "部品在庫を確認済み", "choices": [True, False], "required": True, "operation_ids": ["parts_wait"]},
    ]
}


def build_schema(job: str, rule_pack: dict | None = None) -> dict[str, Any]:
    """Return the versioned public form definition for a job."""
    pack = rule_pack if isinstance(rule_pack, dict) else {}
    definitions = pack.get("form_schemas", FORM_SCHEMAS)
    fields = definitions.get(job) if isinstance(definitions, dict) else None
    return {"schema_id": f"{ENGINE_ID}:{job}", "schema_version": str(pack.get("schema_version", RULE_VERSION)),
            "job_id": job, "fields": deepcopy(fields) if isinstance(fields, list) else []}


def _active(definition: dict[str, Any], fields: dict[str, Any]) -> bool:
    condition = definition.get("required_if")
    if not isinstance(condition, dict):
        return True
    observed = fields.get(condition.get("field"), {})
    value = observed.get("value") if isinstance(observed, dict) else observed
    return value == condition.get("equals")


def _has_value(fields: dict[str, Any], key: str) -> bool:
    item = fields.get(key)
    return isinstance(item, dict) and item.get("value") is not None and item.get("status") in ("confirmed", "declared")


def render_form(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    """Describe fields and ask only for active missing or unknown observations."""
    scenario = scenario_input if isinstance(scenario_input, dict) else {}
    job = scenario.get("job_id")
    schema = build_schema(job, rule_pack)
    fields = scenario.get("fields") if isinstance(scenario.get("fields"), dict) else {}
    questions = []
    for definition in schema["fields"]:
        active = _active(definition, fields)
        current = fields.get(definition["field"])
        unknown = isinstance(current, dict) and current.get("status") == "unknown"
        required = definition.get("required", False) or definition.get("required_if") is not None and active
        if active and required and (not _has_value(fields, definition["field"]) or unknown):
            questions.append(deepcopy(definition))
    return {"schema": schema, "questions": questions}


def _valid_value(definition: dict[str, Any], value: Any) -> bool:
    if definition.get("kind") == "range":
        return (isinstance(value, dict) and set(value) == {"low", "typical", "high"}
                and all(isinstance(value[k], (int, float)) and not isinstance(value[k], bool) and value[k] >= 0 for k in ("low", "typical", "high"))
                and value["low"] <= value["typical"] <= value["high"])
    choices = definition.get("choices")
    if definition.get("multiple"):
        return isinstance(value, list) and len(value) == len(set(value)) and all(v in choices for v in value)
    return value in choices


def apply_answers(scenario_input: dict, answers: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    """Apply explicitly confirmed answers; unknown is retained without inventing a value."""
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    fields = scenario.setdefault("fields", {})
    if not isinstance(fields, dict):
        return {"scenario_input": scenario, "errors": ["fields:object_required"], "approvals": []}
    job = scenario.get("job_id")
    schema = build_schema(job, rule_pack)
    by_key = {item["field"]: item for item in schema["fields"]}
    errors: list[str] = []
    approvals = []
    if not isinstance(answers, dict):
        return {"scenario_input": scenario, "errors": ["answers:object_required"], "approvals": []}
    # Apply selector/driver observations first so conditional fields do not
    # depend on the caller's dictionary insertion order.
    ordered_answers = sorted(answers.items(), key=lambda item: (
        0 if item[0] in {condition.get("field") for definition in by_key.values()
                         for condition in [definition.get("required_if", {})]
                         if isinstance(condition, dict)} else 1))
    for key, answer in ordered_answers:
        definition = by_key.get(key)
        if definition is None:
            errors.append(f"{key}:unknown_field")
            continue
        if not isinstance(answer, dict):
            errors.append(f"{key}:answer_object_required")
            continue
        value = answer.get("value")
        if value == "unknown" or answer.get("status") == "unknown":
            actor, source, confirmed_at = answer.get("actor"), answer.get("source"), answer.get("confirmed_at")
            try:
                date.fromisoformat(confirmed_at[:10]) if isinstance(confirmed_at, str) else None
                valid_date = isinstance(confirmed_at, str) and bool(confirmed_at)
            except ValueError:
                valid_date = False
            if (answer.get("confirmed") is not True or not isinstance(actor, str) or not actor.strip()
                    or not isinstance(source, str) or not source.strip() or not valid_date):
                errors.append(f"{key}:explicit_confirmation_actor_source_date_required")
                continue
            prior = fields.get(key)
            old_value = prior.get("value") if isinstance(prior, dict) else None
            fields[key] = {"value": None, "status": "unknown", "source": source, "confirmed_at": confirmed_at}
            approvals.append({"field": key, "actor": actor, "source": source, "confirmed_at": confirmed_at,
                              "old_value": deepcopy(old_value), "new_value": None})
            continue
        if not _active(definition, fields):
            errors.append(f"{key}:condition_not_active")
            continue
        if not _valid_value(definition, value):
            errors.append(f"{key}:choice_or_value_invalid")
            continue
        actor, source, confirmed_at = answer.get("actor"), answer.get("source"), answer.get("confirmed_at")
        try:
            date.fromisoformat(confirmed_at[:10]) if isinstance(confirmed_at, str) else None
            valid_date = isinstance(confirmed_at, str) and bool(confirmed_at)
        except ValueError:
            valid_date = False
        if answer.get("confirmed") is not True or not isinstance(actor, str) or not actor.strip() or not isinstance(source, str) or not source.strip() or not valid_date:
            errors.append(f"{key}:explicit_confirmation_actor_source_date_required")
            continue
        prior = fields.get(key)
        old_value = prior.get("value") if isinstance(prior, dict) else None
        fields[key] = {"value": deepcopy(value), "status": "confirmed", "source": source, "confirmed_at": confirmed_at}
        approvals.append({"field": key, "actor": actor, "source": source, "confirmed_at": confirmed_at,
                          "old_value": deepcopy(old_value), "new_value": deepcopy(value)})
        if key == "rotor_seizure_hours":
            metadata = scenario.setdefault("metadata", {})
            metadata.setdefault("approved_condition_widths", {})[key] = {
                "actor": actor, "reason": answer.get("reason", "人が条件幅を確認"),
                "old_value": deepcopy(old_value), "new_value": deepcopy(value)}
    return {"scenario_input": scenario, "errors": errors, "approvals": approvals}


def _stopped(unknowns: list[str]) -> dict[str, Any]:
    return {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL), "breakdown": [], "unknowns": list(dict.fromkeys(unknowns))}


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    """Validate schema-required observations, then delegate calculation to E07."""
    original = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    schema_view = render_form(original, rule_pack)
    questions = schema_view["questions"]
    errors = []
    for definition in schema_view["schema"]["fields"]:
        active = _active(definition, original.get("fields", {}) if isinstance(original.get("fields"), dict) else {})
        is_required = definition.get("required", False) or (definition.get("required_if") is not None and active)
        if active and is_required:
            key = definition["field"]
            if not _has_value(original.get("fields", {}), key):
                current = original.get("fields", {}).get(key) if isinstance(original.get("fields"), dict) else None
                suffix = "unknown_confirmation_required" if isinstance(current, dict) and current.get("status") == "unknown" else "required_observation_missing"
                errors.append(f"{key}:{suffix}")
    # Conditional range requires explicit human approval/audit, enforced by E07.
    if errors:
        labor = _stopped(errors)
        status = "missing-required"
        trace = [{"stage": "schema_form", "schema": schema_view["schema"], "questions": questions,
                  "validation_errors": errors, "provenance": deepcopy(original.get("fields", {}))}]
        result = {"engine_id": ENGINE_ID, "rule_version": RULE_VERSION, "status": status, "labor": labor,
                  "trace": trace, "operation_keys": [], "approvals": [], "simulator_notice": SIMULATOR_NOTICE}
        return result
    result = e07.run(deepcopy(original), rule_pack)
    result["engine_id"] = ENGINE_ID
    result["rule_version"] = RULE_VERSION
    result["trace"].append({"stage": "schema_form", "schema": schema_view["schema"], "questions": questions,
                            "validation_errors": [], "provenance": deepcopy(original.get("fields", {}))})
    result["approvals"] = deepcopy(original.get("metadata", {}).get("approved_condition_widths", {})) if isinstance(original.get("metadata"), dict) else []
    result["simulator_notice"] = SIMULATOR_NOTICE
    return result
