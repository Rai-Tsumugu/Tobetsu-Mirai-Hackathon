"""E04: normalized, version-pinned SQLite rules for fictional labor estimates."""
from __future__ import annotations

from copy import deepcopy
import sqlite3
from typing import Any

from .contract import reference_labor

ENGINE_ID = "e04_sqlite_normalized"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_BANDS = ("low", "typical", "high")
_DEFAULT_RULES = (
    ("base_service", "承認済み基準作業", "work", "person_hours", (1.7, 1.7, 1.7), 1),
    ("included_carry", "含有運搬", "work", "person_hours", (0.12, 0.12, 0.12), 1),
    ("replacement_carry", "二人作業の運搬", "work", "person_hours", (0.2, 0.2, 0.2), 2),
    ("rotor_seizure", "ローター固着", "work", "person_hours", (0.0, 0.25, 0.5), 1),
    ("snow_melt", "雪の融解待ち", "wait", "elapsed_hours", (0.5, 0.5, 0.5), 0),
    ("penetrant_wait", "浸透待ち", "wait", "elapsed_hours", (0.25, 0.25, 0.25), 0),
    ("parts_wait", "部品待ち", "wait", "elapsed_hours", (0.0, 0.0, 0.0), 0),
    ("wash", "洗浄", "work", "person_hours", (0.1, 0.1, 0.1), 1),
)


def create_database() -> sqlite3.Connection:
    """Return a fresh in-memory database with foreign-key checks enabled."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create the normalized rule, operation, relation, and evidence tables."""
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS rules (
            id TEXT NOT NULL,
            version TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('approved', 'draft')),
            approved_by TEXT,
            effective_from TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY (id, version)
        );
        CREATE TABLE IF NOT EXISTS operations (
            id TEXT PRIMARY KEY,
            operation_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('work', 'wait')),
            unit TEXT NOT NULL CHECK (unit IN ('person_hours', 'elapsed_hours'))
        );
        CREATE TABLE IF NOT EXISTS rule_operations (
            rule_id TEXT NOT NULL,
            version TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            low REAL NOT NULL CHECK (low >= 0),
            typical REAL NOT NULL CHECK (typical >= low),
            high REAL NOT NULL CHECK (high >= typical),
            person_count INTEGER NOT NULL CHECK (person_count >= 0),
            PRIMARY KEY (rule_id, version, operation_id),
            FOREIGN KEY (rule_id, version) REFERENCES rules(id, version),
            FOREIGN KEY (operation_id) REFERENCES operations(id)
        );
        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            version TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            source TEXT NOT NULL,
            note TEXT NOT NULL,
            PRIMARY KEY (id, rule_id, version, operation_id),
            FOREIGN KEY (rule_id, version, operation_id)
                REFERENCES rule_operations(rule_id, version, operation_id)
        );
        CREATE TRIGGER IF NOT EXISTS rules_immutable_update
        BEFORE UPDATE ON rules BEGIN
            SELECT RAISE(ABORT, 'published rule versions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS rules_immutable_delete
        BEFORE DELETE ON rules BEGIN
            SELECT RAISE(ABORT, 'published rule versions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS operations_immutable_update
        BEFORE UPDATE ON operations BEGIN
            SELECT RAISE(ABORT, 'operation definitions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS operations_immutable_delete
        BEFORE DELETE ON operations BEGIN
            SELECT RAISE(ABORT, 'operation definitions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS rule_operations_immutable_update
        BEFORE UPDATE ON rule_operations BEGIN
            SELECT RAISE(ABORT, 'published rule operations are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS rule_operations_immutable_delete
        BEFORE DELETE ON rule_operations BEGIN
            SELECT RAISE(ABORT, 'published rule operations are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS evidence_immutable_update
        BEFORE UPDATE ON evidence BEGIN
            SELECT RAISE(ABORT, 'published evidence is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS evidence_immutable_delete
        BEFORE DELETE ON evidence BEGIN
            SELECT RAISE(ABORT, 'published evidence is immutable');
        END;
        """
    )


def _rule_version(pack: dict[str, Any]) -> str:
    version = pack.get("rule_version", pack.get("version"))
    if not isinstance(version, str) or not version.strip():
        raise ValueError("rule_pack requires a non-empty rule_version")
    return version


def _normalize_range(value: Any, unit: str) -> tuple[float, float, float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = {band: float(value) for band in _BANDS}
    if not isinstance(value, dict) or set(value) != set(_BANDS):
        raise ValueError("hours must be a number or a low/typical/high object")
    numbers: list[float] = []
    for band in _BANDS:
        raw = value[band]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"hours.{band} must be numeric")
        number = float(raw)
        if number < 0 or number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"hours.{band} must be finite and non-negative")
        numbers.append(number)
    if numbers != sorted(numbers):
        raise ValueError("hours must satisfy low <= typical <= high")
    return numbers[0], numbers[1], numbers[2]


def publish_rule_pack(connection: sqlite3.Connection, rule_pack: dict[str, Any]) -> str:
    """Insert one immutable normalized rule version atomically.

    Duplicate operations or broken references fail the whole save.  A prior
    version remains available for replay and cannot be updated in place.
    """
    if not isinstance(rule_pack, dict):
        raise ValueError("rule_pack must be an object")
    version = _rule_version(rule_pack)
    rule_id = str(rule_pack.get("id", "fictional_labor_rules"))
    status = rule_pack.get("status", "approved")
    if status not in ("approved", "draft"):
        raise ValueError("rule_pack status must be approved or draft")
    approved_by = rule_pack.get("approved_by")
    if status == "approved" and (not isinstance(approved_by, str) or not approved_by.strip()):
        raise ValueError("approved rule_pack requires approved_by")
    effective_from = rule_pack.get("effective_from", "2026-10-11")
    source = rule_pack.get("source", "fictional_simulator_fixture")
    entries = rule_pack.get("rules")
    if not isinstance(entries, list) or not entries:
        raise ValueError("rule_pack rules must be a non-empty list")

    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("SAVEPOINT e04_publish")
    try:
        connection.execute(
            "INSERT INTO rules(id, version, status, approved_by, effective_from, source) VALUES (?, ?, ?, ?, ?, ?)",
            (rule_id, version, status, approved_by, effective_from, source),
        )
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(f"rule_pack rules[{index}] must be an object")
            operation_id = entry.get("operation_id")
            operation_key = entry.get("operation_key", operation_id)
            name = entry.get("operation", operation_id)
            kind = entry.get("kind", "wait" if entry.get("unit") == "elapsed_hours" else "work")
            unit = entry.get("unit", "elapsed_hours" if kind == "wait" else "person_hours")
            if not all(isinstance(item, str) and item.strip() for item in (operation_id, operation_key, name)):
                raise ValueError(f"rule_pack rules[{index}] requires operation_id, operation_key, and operation")
            if operation_id in seen:
                raise ValueError(f"duplicate operation_id: {operation_id}")
            seen.add(operation_id)
            if kind not in ("work", "wait") or unit != ("elapsed_hours" if kind == "wait" else "person_hours"):
                raise ValueError(f"invalid kind/unit for operation: {operation_id}")
            person_count = entry.get("person_count", 0 if kind == "wait" else 1)
            if isinstance(person_count, bool) or not isinstance(person_count, int) or person_count < 0:
                raise ValueError(f"person_count must be a non-negative integer: {operation_id}")
            low, typical, high = _normalize_range(entry.get("hours"), unit)
            connection.execute(
                "INSERT INTO operations(id, operation_key, name, kind, unit) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO NOTHING",
                (operation_id, operation_key, name, kind, unit),
            )
            existing = connection.execute("SELECT operation_key, kind, unit FROM operations WHERE id = ?", (operation_id,)).fetchone()
            if tuple(existing) != (operation_key, kind, unit):
                raise ValueError(f"operation definition conflicts with existing id: {operation_id}")
            connection.execute(
                "INSERT INTO rule_operations(rule_id, version, operation_id, low, typical, high, person_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rule_id, version, operation_id, low, typical, high, person_count),
            )
            evidence_rows = entry.get("evidence") or [{"source": entry.get("source", source), "note": "架空のSimulator用規則"}]
            for evidence_index, item in enumerate(evidence_rows):
                if not isinstance(item, dict) or not isinstance(item.get("source"), str) or not item["source"].strip():
                    raise ValueError(f"evidence source required for operation: {operation_id}")
                note = item.get("note", "")
                if not isinstance(note, str):
                    raise ValueError(f"evidence note must be a string: {operation_id}")
                evidence_id = item.get("id", f"{operation_id}-evidence-{evidence_index + 1}")
                connection.execute(
                    "INSERT INTO evidence(id, rule_id, version, operation_id, source, note) VALUES (?, ?, ?, ?, ?, ?)",
                    (evidence_id, rule_id, version, operation_id, item["source"], note),
                )
        connection.execute("RELEASE SAVEPOINT e04_publish")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT e04_publish")
        connection.execute("RELEASE SAVEPOINT e04_publish")
        raise
    return version


def seed_default_rule_pack(connection: sqlite3.Connection, version: str = "fictional-rule-v1") -> None:
    """Install the documented all-fictional common comparison pack."""
    entries = []
    for operation_id, name, kind, unit, numbers, person_count in _DEFAULT_RULES:
        entries.append({
            "operation_id": operation_id,
            "operation_key": operation_id,
            "operation": name,
            "kind": kind,
            "unit": unit,
            "hours": dict(zip(_BANDS, numbers)),
            "person_count": person_count,
            "source": "fictional_simulator_fixture",
            "evidence": [{"source": "fictional_simulator_fixture", "note": "架空の比較用fixture。実測値ではない"}],
        })
    publish_rule_pack(connection, {
        "id": "fictional_labor_rules", "rule_version": version, "status": "approved",
        "approved_by": "fictional_shop_owner", "effective_from": "2026-10-11",
        "source": "fictional_simulator_fixture", "rules": entries,
    })


def _load_joined_rules(connection: sqlite3.Connection, rule_id: str, version: str) -> tuple[sqlite3.Row | None, list[sqlite3.Row]]:
    rule = connection.execute("SELECT * FROM rules WHERE id = ? AND version = ?", (rule_id, version)).fetchone()
    if not rule:
        return None, []
    rows = connection.execute(
        """SELECT ro.operation_id, o.operation_key, o.name, o.kind, o.unit,
                  ro.low, ro.typical, ro.high, ro.person_count,
                  e.source AS evidence_source, e.note AS evidence_note
           FROM rule_operations AS ro
           JOIN rules AS r ON r.id = ro.rule_id AND r.version = ro.version
           JOIN operations AS o ON o.id = ro.operation_id
           LEFT JOIN evidence AS e ON e.rule_id = ro.rule_id AND e.version = ro.version
                                   AND e.operation_id = ro.operation_id
           WHERE r.id = ? AND r.version = ?
           ORDER BY ro.operation_id, e.id""",
        (rule_id, version),
    ).fetchall()
    return rule, rows


def _observation(scenario: dict[str, Any], key: str) -> tuple[Any, str]:
    value = (scenario.get("fields") or {}).get(key)
    if isinstance(value, dict) and "value" in value:
        return value.get("value"), value.get("status", "unknown")
    return value, "declared" if value is not None else "unknown"


def run(scenario_input: dict, rule_pack: dict | None = None,
        connection: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Calculate using a pinned version read through normalized SQLite JOINs.

    A caller can supply a connection to replay prior versions.  Without one,
    each call uses a fresh in-memory DB seeded with the fictional default pack.
    Passing a pack inserts it atomically into that connection before lookup.
    """
    if not isinstance(scenario_input, dict):
        raise TypeError("scenario_input must be an object")
    scenario = deepcopy(scenario_input)
    own_connection = connection is None
    db = connection or create_database()
    db.row_factory = sqlite3.Row
    initialize_database(db)
    if own_connection and rule_pack is None:
        seed_version = scenario.get("rule_version") or "fictional-rule-v1"
        seed_default_rule_pack(db, seed_version)

    pinned_version = scenario.get("rule_version")
    if rule_pack is not None:
        try:
            pack_version = publish_rule_pack(db, deepcopy(rule_pack))
        except Exception as error:
            nulls = {band: None for band in _BANDS}
            return {"engine_id": ENGINE_ID, "rule_version": pinned_version or "unbound",
                    "status": "missing-required", "labor": {"person_hours": dict(nulls), "elapsed_hours": dict(nulls),
                    "breakdown": [], "unknowns": [f"rule_pack:database_write_failed:{type(error).__name__}"]},
                    "trace": [{"event": "rule_pack_transaction_rolled_back"}], "operation_keys": [],
                    "approvals": [], "simulator_notice": SIMULATOR_NOTICE}
        if pinned_version and pack_version != pinned_version:
            version_gap = "rule_pack:pinned_version_mismatch"
        else:
            version_gap = None
    else:
        version_gap = None

    version = pinned_version or (rule_pack and _rule_version(rule_pack)) or "fictional-rule-v1"
    rule_id = (rule_pack or {}).get("id", "fictional_labor_rules")
    # Keep the rule header and its JOINed operations/evidence on one SQLite
    # snapshot so a concurrent publisher cannot mix versions during a run.
    db.execute("SAVEPOINT e04_read")
    try:
        rule, joined = _load_joined_rules(db, rule_id, version)
        db.execute("RELEASE SAVEPOINT e04_read")
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT e04_read")
        db.execute("RELEASE SAVEPOINT e04_read")
        raise
    grouped: dict[str, dict[str, Any]] = {}
    for row in joined:
        item = grouped.setdefault(row["operation_id"], {
            "operation_id": row["operation_id"], "operation_key": row["operation_key"], "operation": row["name"],
            "kind": row["kind"], "unit": row["unit"], "hours": {band: row[band] for band in _BANDS},
            "person_count": row["person_count"], "evidence": [],
        })
        if row["evidence_source"] and not any(ev["source"] == row["evidence_source"] and ev["note"] == row["evidence_note"] for ev in item["evidence"]):
            item["evidence"].append({"source": row["evidence_source"], "note": row["evidence_note"]})

    labor, _, canonical_unknowns = reference_labor(scenario)
    unknowns = list(canonical_unknowns)
    if not rule:
        unknowns.append(f"rule_pack:version_not_found:{version}")
    elif rule["status"] != "approved":
        unknowns.append("rule_pack:approved_status_required")
    if version_gap:
        unknowns.append(version_gap)
    rotor_relevance, _ = _observation(scenario, "rotor_relevance")
    if rotor_relevance == "relevant":
        rotor_value, rotor_status = _observation(scenario, "rotor_seizure_hours")
        approval = (scenario.get("metadata") or {}).get("approved_condition_widths", {}).get("rotor_seizure_hours")
        stored_rotor = grouped.get("rotor_seizure", {}).get("hours")
        if (rotor_status != "confirmed" or not isinstance(rotor_value, dict)
                or set(rotor_value) != set(_BANDS) or not isinstance(approval, dict)
                or approval.get("new_value") != rotor_value or stored_rotor != rotor_value):
            unknowns.append("rotor_seizure_hours:rule_approval_mismatch")
    required_ids = {entry[0] for entry in _DEFAULT_RULES}
    for operation_id in sorted(required_ids - set(grouped)):
        unknowns.append(f"{operation_id}:rule_missing")

    trace: list[dict[str, Any]] = [{"event": "rule_version_pinned", "rule_id": rule_id, "rule_version": version}]
    for operation_id in sorted(grouped):
        item = grouped[operation_id]
        trace.append({"event": "rule_operation_joined", "operation_id": operation_id,
                      "operation_key": item["operation_key"], "hours": dict(item["hours"]),
                      "unit": item["unit"], "rule_version": version, "evidence": deepcopy(item["evidence"])})

    rows_by_id = {row.get("operation_id"): row for row in labor.get("breakdown", []) if row.get("operation_id")}
    if not unknowns:
        # Apply joined values, including the included-work credit and person count.
        # The canonical reference calculator remains the authority for required
        # fields, rotor approval, and wait/elapsed separation.
        for operation_id in required_ids:
            item = grouped[operation_id]
            row = rows_by_id.get(operation_id)
            if row is None:
                continue
            hours = dict(item["hours"])
            row["operation"] = item["operation"]
            row["evidence_refs"] = [ev["source"] for ev in item["evidence"]]
            row["rule_version"] = version
            if operation_id == "included_carry":
                row["operation_key"] = "included_transport_removed"
                row["hours"] = {band: 0.0 for band in _BANDS}
                trace.append({"event": "included_hours_credited", "operation_id": operation_id,
                              "hours": hours, "rule_version": version})
            elif item["kind"] == "wait":
                row["status"] = "wait"
                row["hours"] = {band: 0.0 for band in _BANDS}
                row["elapsed_hours"] = hours
            elif operation_id == "rotor_seizure" and _observation(scenario, "rotor_relevance")[0] == "unrelated":
                row["hours"] = {band: 0.0 for band in _BANDS}
            else:
                row["hours"] = hours
                if operation_id == "rotor_seizure" and row.get("status") == "conditional":
                    row["status"] = "conditional"

        included = grouped["included_carry"]["hours"]
        base = grouped["base_service"]["hours"]
        replacement = grouped["replacement_carry"]["hours"]
        person = {band: 0.0 for band in _BANDS}
        elapsed = {band: 0.0 for band in _BANDS}
        for band in _BANDS:
            net_base = base[band] - included[band]
            if net_base < 0:
                unknowns.append("included_transport:credit_exceeds_base")
            person[band] += net_base + replacement[band]
            elapsed[band] += net_base + replacement[band] / max(1, grouped["replacement_carry"]["person_count"])
            wash = grouped["wash"]["hours"][band]
            person[band] += wash
            elapsed[band] += wash
            if rotor_relevance == "relevant":
                rotor = grouped["rotor_seizure"]["hours"][band]
                person[band] += rotor
                elapsed[band] += rotor
            for operation_id in ("snow_melt", "penetrant_wait", "parts_wait"):
                elapsed[band] += grouped[operation_id]["hours"][band]
        if not unknowns:
            labor["person_hours"] = {band: round(person[band], 10) for band in _BANDS}
            labor["elapsed_hours"] = ({band: None for band in _BANDS}
                                       if any(value.endswith(":elapsed_duration_unknown") for value in canonical_unknowns)
                                       else {band: round(elapsed[band], 10) for band in _BANDS})

    blocking = [value for value in unknowns if not value.endswith(":elapsed_duration_unknown")]
    if blocking:
        nulls = {band: None for band in _BANDS}
        labor["person_hours"] = dict(nulls)
        labor["elapsed_hours"] = dict(nulls)
        for row in labor.get("breakdown", []):
            row["hours"] = dict(nulls)
            if "elapsed_hours" in row:
                row["elapsed_hours"] = dict(nulls)
            row["status"] = "missing-required"
    labor["unknowns"] = list(dict.fromkeys(unknowns))

    approvals = []
    if rule and rule["status"] == "approved":
        approvals.append({"type": "rule_pack", "approver": rule["approved_by"],
                          "effective_from": rule["effective_from"], "source": rule["source"],
                          "rule_version": version})
    approval = (scenario.get("metadata") or {}).get("approved_condition_widths", {}).get("rotor_seizure_hours")
    if approval and _observation(scenario, "rotor_relevance")[0] == "relevant":
        approvals.append({"operation_key": "rotor_seizure", "actor": approval.get("actor"),
                          "reason": approval.get("reason"), "old_value": deepcopy(approval.get("old_value")),
                          "new_value": deepcopy(approval.get("new_value")),
                          "applied_range": deepcopy(grouped.get("rotor_seizure", {}).get("hours")),
                          "rule_version": version})
    operation_keys = list(dict.fromkeys(item["operation_key"] for item in grouped.values()))
    status = "missing-required" if blocking else ("partial" if unknowns else "proposed")
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": status, "labor": labor,
            "trace": trace, "operation_keys": operation_keys, "approvals": approvals,
            "simulator_notice": SIMULATOR_NOTICE}
