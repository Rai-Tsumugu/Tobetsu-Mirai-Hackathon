"""E05: validate, preview, and publish immutable CSV rule packs."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from math import isfinite
from typing import Any

from . import e02
from .contract import common_scenario_fixture

ENGINE_ID = "e05_csv_import"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
CSV_COLUMNS = ("job_id", "operation_key", "condition_field", "match_value",
               "low", "typical", "high", "unit", "source", "reason")
RULE_KEYS = frozenset({"base_service", "replacement_carry", "snow_melt", "penetrant_wait",
                       "parts_wait", "wash", "rotor_seizure"})
_ALLOWED_FIELDS = frozenset({"work_scope", "included_operations", "parts_wait_stock_checked", "rotor_relevance"})
_ELAPSED_KEYS = frozenset({"snow_melt", "penetrant_wait", "parts_wait"})
_PUBLISHED: dict[str, "PublishedRulePack"] = {}


@dataclass(frozen=True)
class RuleRow:
    job_id: str
    operation_key: str
    condition_field: str
    match_value: str
    low: float
    typical: float
    high: float
    unit: str
    source: str
    reason: str

    def hours(self) -> dict[str, float]:
        return {"low": self.low, "typical": self.typical, "high": self.high}

    def condition(self) -> dict[str, Any]:
        value: Any = self.match_value
        if self.condition_field == "parts_wait_stock_checked":
            value = self.match_value.strip().lower() == "true"
        if self.condition_field == "included_operations":
            return {"field": self.condition_field, "contains": value}
        return {"field": self.condition_field, "equals": value}


def _row_snapshot(row: RuleRow) -> dict[str, Any]:
    """Capture every CSV rule attribute that can affect selection or trust."""
    return {
        "job_id": row.job_id,
        "operation_key": row.operation_key,
        "condition": row.condition(),
        "hours": row.hours(),
        "unit": row.unit,
        "source": row.source,
        "reason": row.reason,
    }


@dataclass(frozen=True)
class ImportBatch:
    hash: str
    rows: tuple[RuleRow, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ApprovalAudit:
    actor: str
    reason: str
    operation_key: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any]


@dataclass(frozen=True)
class PublishedRulePack:
    engine_id: str
    rule_version: str
    effective_from: str
    source: str
    basis_unit: str
    basis_definition: str
    import_hash: str
    snapshot_hash: str
    approved_by: str
    approval_reason: str
    rules: tuple[RuleRow, ...]
    audit: tuple[ApprovalAudit, ...]

    def to_rule_pack(self) -> dict[str, Any]:
        """Return a fresh E02-compatible snapshot for the calculation adapter."""
        return {
            "engine_id": e02.ENGINE_ID,
            "rule_version": self.rule_version,
            "status": "approved",
            "approved_by": self.approved_by,
            "effective_from": self.effective_from,
            "source": self.source,
            "basis_unit": self.basis_unit,
            "basis_definition": self.basis_definition,
            "rules": [
                {"job_id": row.job_id, "operation_key": row.operation_key,
                 "condition": row.condition(), "hours": row.hours(), "unit": row.unit,
                 "source": row.source}
                for row in self.rules
            ],
        }


def parse_csv(content: str | bytes) -> ImportBatch:
    """Parse plain numeric CSV; formulas and unsupported columns are rejected."""
    if isinstance(content, bytes):
        raw = content
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return ImportBatch(hashlib.sha256(raw).hexdigest(), (), ("csv:invalid_utf8",))
    elif isinstance(content, str):
        text = content
        raw = content.encode("utf-8")
    else:
        raise TypeError("content must be str or bytes")

    digest = hashlib.sha256(raw).hexdigest()
    errors: list[str] = []
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        return ImportBatch(digest, (), ("csv:header_required",))
    headers = tuple(header.strip() for header in reader.fieldnames)
    if len(headers) != len(set(headers)) or set(headers) != set(CSV_COLUMNS):
        errors.append("csv:header_mismatch")
        return ImportBatch(digest, (), tuple(errors))

    rows: list[RuleRow] = []
    for index, raw_row in enumerate(reader, start=2):
        if None in raw_row:
            errors.append(f"row:{index}:extra_columns")
            continue
        row = {key: (raw_row.get(key) or "").strip() for key in CSV_COLUMNS}
        try:
            values = [float(row[key]) for key in ("low", "typical", "high")]
        except ValueError:
            errors.append(f"row:{index}:invalid_numeric_range")
            continue
        if any(not isfinite(value) or value < 0 for value in values):
            errors.append(f"row:{index}:invalid_numeric_range")
            continue
        rows.append(RuleRow(
            job_id=row["job_id"], operation_key=row["operation_key"],
            condition_field=row["condition_field"], match_value=row["match_value"],
            low=values[0], typical=values[1], high=values[2], unit=row["unit"],
            source=row["source"], reason=row["reason"],
        ))
    return ImportBatch(digest, tuple(rows), tuple(errors))


def validate_units(batch: ImportBatch) -> tuple[str, ...]:
    """Validate range order, operation names, units, keys, and required metadata."""
    errors = list(batch.errors)
    seen: set[str] = set()
    for index, row in enumerate(batch.rows, start=2):
        prefix = f"row:{index}"
        if row.operation_key not in RULE_KEYS:
            errors.append(f"{prefix}:unknown_operation_key:{row.operation_key}")
        elif row.operation_key in seen:
            errors.append(f"{prefix}:duplicate_operation_key:{row.operation_key}")
        seen.add(row.operation_key)
        if (not row.job_id or not row.condition_field or not row.match_value
                or not row.source or not row.reason):
            errors.append(f"{prefix}:required_value_missing")
        if row.condition_field not in _ALLOWED_FIELDS:
            errors.append(f"{prefix}:unknown_condition_field:{row.condition_field}")
        if (row.condition_field == "parts_wait_stock_checked"
                and row.match_value.strip().lower() not in {"true", "false"}):
            errors.append(f"{prefix}:invalid_boolean_condition:{row.condition_field}")
        expected_unit = "elapsed_hours" if row.operation_key in _ELAPSED_KEYS else "person_hours"
        if row.unit != expected_unit:
            errors.append(f"{prefix}:unit_mismatch:{row.operation_key}")
        values = (row.low, row.typical, row.high)
        if (any(not isfinite(value) or value < 0 for value in values)
                or not row.low <= row.typical <= row.high):
            errors.append(f"{prefix}:invalid_or_misaligned_range")
    for missing in sorted(RULE_KEYS - seen):
        errors.append(f"rule:{missing}:required")
    return tuple(dict.fromkeys(errors))


def preview_diff(batch: ImportBatch, previous: PublishedRulePack | None = None) -> dict[str, Any]:
    """Return validation results and a stable per-operation preview."""
    old = {row.operation_key: row for row in previous.rules} if previous else {}
    new = {row.operation_key: row for row in batch.rows}
    changes = []
    for key in sorted(set(old) | set(new)):
        before, after = old.get(key), new.get(key)
        old_value = _row_snapshot(before) if before else None
        new_value = _row_snapshot(after) if after else None
        if old_value != new_value:
            changes.append({"operation_key": key, "old_value": old_value,
                            "new_value": new_value})
    return {"import_hash": batch.hash, "errors": list(validate_units(batch)),
            "changes": changes}


def human_publish(batch: ImportBatch, actor: str, reason: str, rule_version: str,
                  effective_from: str, basis_unit: str, basis_definition: str,
                  previous: PublishedRulePack | None = None) -> PublishedRulePack:
    """Publish a validated snapshot only with a named approver and reason."""
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("publish:actor_required")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("publish:reason_required")
    if not isinstance(rule_version, str) or not rule_version.strip():
        raise ValueError("publish:rule_version_required")
    if not isinstance(effective_from, str) or not effective_from.strip():
        raise ValueError("publish:effective_from_required")
    if not basis_unit or not basis_definition:
        raise ValueError("publish:basis_required")
    errors = validate_units(batch)
    if errors:
        raise ValueError("publish:validation_failed:" + ",".join(errors))

    old = {row.operation_key: row for row in previous.rules} if previous else {}
    audits = []
    for row in batch.rows:
        prior = old.get(row.operation_key)
        old_value = _row_snapshot(prior) if prior else None
        new_value = _row_snapshot(row)
        if old_value != new_value:
            audits.append(ApprovalAudit(actor.strip(), reason.strip(), row.operation_key,
                                        old_value, new_value))
    snapshot = {
        "engine_id": ENGINE_ID, "rule_version": rule_version.strip(),
        "effective_from": effective_from.strip(), "source": "csv_import",
        "basis_unit": basis_unit, "basis_definition": basis_definition,
        "import_hash": batch.hash,
        "rules": [{"job_id": row.job_id, "operation_key": row.operation_key,
                   "condition": row.condition(), "hours": row.hours(), "unit": row.unit,
                   "source": row.source, "reason": row.reason} for row in batch.rows],
    }
    snapshot_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                                               separators=(",", ":")).encode("utf-8")).hexdigest()
    existing = _PUBLISHED.get(rule_version.strip())
    if existing and existing.snapshot_hash != snapshot_hash:
        raise ValueError("publish:published_version_is_immutable")
    if existing:
        return existing
    published = PublishedRulePack(
        engine_id=ENGINE_ID, rule_version=rule_version.strip(),
        effective_from=effective_from.strip(), source="csv_import:" + batch.hash,
        basis_unit=basis_unit, basis_definition=basis_definition,
        import_hash=batch.hash, snapshot_hash=snapshot_hash,
        approved_by=actor.strip(), approval_reason=reason.strip(),
        rules=tuple(batch.rows), audit=tuple(audits),
    )
    _PUBLISHED[published.rule_version] = published
    return published


_DEFAULT_CSV = """job_id,operation_key,condition_field,match_value,low,typical,high,unit,source,reason
front_brake_service,base_service,work_scope,front_brake_service,1.7,1.7,1.7,person_hours,fictional_csv:base,fictional deduplicated base
front_brake_service,replacement_carry,included_operations,remove_install,0.2,0.2,0.2,person_hours,fictional_csv:carry,replaces included transport
front_brake_service,snow_melt,included_operations,snow_removal,0.5,0.5,0.5,elapsed_hours,fictional_csv:snow,elapsed wait only
front_brake_service,penetrant_wait,work_scope,front_brake_service,0.25,0.25,0.25,elapsed_hours,fictional_csv:penetrant,elapsed wait only
front_brake_service,parts_wait,parts_wait_stock_checked,true,0,0,0,elapsed_hours,fictional_csv:parts,stock checked elapsed wait
front_brake_service,wash,work_scope,front_brake_service,0.1,0.1,0.1,person_hours,fictional_csv:wash,performed nonbillable work
front_brake_service,rotor_seizure,rotor_relevance,relevant,0,0.25,0.5,person_hours,fictional_csv:rotor,human approved fictional condition width
"""


def _default_pack(scenario: dict[str, Any]) -> PublishedRulePack:
    batch = parse_csv(_DEFAULT_CSV)
    fixture = common_scenario_fixture()
    return human_publish(
        batch, "fictional_shop_owner", "fictional fixture approval", "fictional-rule-v1",
        "2026-10-11T00:00:00+00:00", fixture["basis_unit"], fixture["basis_definition"])


def _snapshot_hash(pack: PublishedRulePack) -> str:
    snapshot = {
        "engine_id": ENGINE_ID, "rule_version": pack.rule_version,
        "effective_from": pack.effective_from, "source": "csv_import",
        "basis_unit": pack.basis_unit, "basis_definition": pack.basis_definition,
        "import_hash": pack.import_hash,
        "rules": [{"job_id": row.job_id, "operation_key": row.operation_key,
                   "condition": row.condition(), "hours": row.hours(), "unit": row.unit,
                   "source": row.source, "reason": row.reason} for row in pack.rules],
    }
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _pack_integrity_errors(pack: PublishedRulePack) -> list[str]:
    """Validate the supplied immutable snapshot and its required approval evidence.

    The digest detects accidental or fabricated inconsistency in this simulator's
    snapshot contract; it is not a signature or proof of an actor's identity.
    """
    errors: list[str] = []
    if (pack.engine_id != ENGINE_ID or not isinstance(pack.rule_version, str)
            or not pack.rule_version.strip()):
        errors.append("published_pack:identity_required")
    if not isinstance(pack.effective_from, str) or not pack.effective_from.strip():
        errors.append("published_pack:effective_from_required")
    if (not isinstance(pack.source, str) or pack.source != "csv_import:" + pack.import_hash
            or not isinstance(pack.import_hash, str)
            or len(pack.import_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in pack.import_hash)):
        errors.append("published_pack:import_hash_or_source_invalid")
    if not isinstance(pack.basis_unit, str) or not pack.basis_unit.strip() or not isinstance(pack.basis_definition, str) or not pack.basis_definition.strip():
        errors.append("published_pack:basis_required")
    if not isinstance(pack.approved_by, str) or not pack.approved_by.strip():
        errors.append("published_pack:approver_required")
    if not isinstance(pack.approval_reason, str) or not pack.approval_reason.strip():
        errors.append("published_pack:approval_reason_required")
    if not isinstance(pack.rules, tuple) or not all(isinstance(row, RuleRow) for row in pack.rules):
        errors.append("published_pack:rules_invalid")
    else:
        batch = ImportBatch(pack.import_hash, pack.rules, ())
        errors.extend("published_" + error for error in validate_units(batch))

    expected_audits: dict[str, dict[str, Any]] = {}
    if isinstance(pack.rules, tuple) and all(isinstance(row, RuleRow) for row in pack.rules):
        for row in pack.rules:
            expected_audits[row.operation_key] = _row_snapshot(row)
    if not isinstance(pack.audit, tuple) or not pack.audit:
        errors.append("published_pack:required_approval_audit_missing")
    else:
        audited_keys: set[str] = set()
        for audit in pack.audit:
            if not isinstance(audit, ApprovalAudit):
                errors.append("published_pack:approval_audit_invalid")
                continue
            expected_new = expected_audits.get(audit.operation_key)
            if (not isinstance(audit.actor, str) or not audit.actor.strip()
                    or not isinstance(audit.reason, str) or not audit.reason.strip()
                    or not expected_new or audit.operation_key in audited_keys
                    or (audit.old_value is not None and not isinstance(audit.old_value, dict))
                    or audit.new_value != expected_new):
                errors.append("published_pack:approval_audit_mismatch")
            audited_keys.add(audit.operation_key)
        if not audited_keys:
            errors.append("published_pack:required_approval_audit_missing")
    if (isinstance(pack.snapshot_hash, str) and len(pack.snapshot_hash) == 64
            and pack.snapshot_hash == _snapshot_hash(pack)):
        pass
    else:
        errors.append("published_pack:snapshot_hash_mismatch")
    return list(dict.fromkeys(errors))


def run(scenario_input: dict, rule_pack: PublishedRulePack | None = None) -> dict:
    """Evaluate a published CSV snapshot under the common C calculation contract."""
    scenario = json.loads(json.dumps(scenario_input))
    pack = _default_pack(scenario) if rule_pack is None else rule_pack
    if not isinstance(pack, PublishedRulePack):
        result = e02.run(scenario, None)
        result["engine_id"] = ENGINE_ID
        result["trace"].append({"event": "csv_import_rejected", "reason": "published_pack_required"})
        return result
    integrity_errors = _pack_integrity_errors(pack)
    if integrity_errors:
        result = e02.run(scenario, None)
        result["engine_id"] = ENGINE_ID
        result["rule_version"] = scenario.get("rule_version") or pack.rule_version
        result["trace"].append({"event": "csv_import_rejected", "reason": "published_pack_integrity_failed",
                                "errors": integrity_errors, "import_hash": pack.import_hash})
        return result
    if scenario.get("rule_version") and scenario["rule_version"] != pack.rule_version:
        result = e02.run(scenario, None)
        result["engine_id"] = ENGINE_ID
        result["rule_version"] = scenario["rule_version"]
        result["trace"].append({"event": "csv_import_rejected", "reason": "pinned_version_mismatch",
                                "requested_version": scenario["rule_version"],
                                "snapshot_version": pack.rule_version,
                                "import_hash": pack.import_hash})
        return result
    if pack.basis_unit != scenario.get("basis_unit") or pack.basis_definition != scenario.get("basis_definition"):
        result = e02.run(scenario, None)
        result["engine_id"] = ENGINE_ID
        result["rule_version"] = scenario.get("rule_version") or pack.rule_version
        result["trace"].append({"event": "csv_import_rejected", "reason": "basis_mismatch",
                                "import_hash": pack.import_hash})
        return result
    underlying = e02.run(scenario, pack.to_rule_pack())
    underlying["engine_id"] = ENGINE_ID
    underlying["trace"].insert(0, {"event": "csv_snapshot_loaded", "import_hash": pack.import_hash,
                                   "snapshot_hash": pack.snapshot_hash,
                                   "rule_version": pack.rule_version})
    underlying["trace"].append({"event": "csv_diff_reviewed", "operation_keys": [r.operation_key for r in pack.rules]})
    underlying["approvals"].insert(0, {
        "type": "csv_publish", "actor": pack.approved_by,
        "reason": pack.approval_reason, "import_hash": pack.import_hash,
        "snapshot_hash": pack.snapshot_hash, "rule_version": pack.rule_version,
        "changes": [{"operation_key": item.operation_key,
                     "old_value": item.old_value,
                     "new_value": item.new_value, "actor": item.actor,
                     "reason": item.reason} for item in pack.audit],
    })
    return underlying
