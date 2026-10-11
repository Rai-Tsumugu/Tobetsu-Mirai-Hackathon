"""SQLite persistence for simulator scenarios, estimates, approvals, and audit events."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).with_name("auto_repair_simulator.sqlite3")


class AutoRepairStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS rule_packs (
                    engine_id TEXT NOT NULL, rule_version TEXT NOT NULL, body_json TEXT NOT NULL,
                    approved_by TEXT, effective_from TEXT, status TEXT NOT NULL,
                    PRIMARY KEY(engine_id, rule_version)
                );
                CREATE TABLE IF NOT EXISTS estimates (
                    estimate_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, engine_id TEXT NOT NULL,
                    rule_version TEXT NOT NULL, status TEXT NOT NULL, body_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS estimate_idempotency (
                    idempotency_key TEXT PRIMARY KEY, estimate_id TEXT NOT NULL, body_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS observation_events (
                    event_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, operation_id TEXT,
                    event_type TEXT NOT NULL, body_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS estimate_revisions (
                    revision_id TEXT PRIMARY KEY, estimate_id TEXT NOT NULL, supersedes_revision_id TEXT,
                    reason TEXT NOT NULL, body_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS offline_snapshots (
                    snapshot_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, rule_version TEXT NOT NULL,
                    body_json TEXT NOT NULL, sync_status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def save_estimate(self, estimate_id: str, result: dict[str, Any], idempotency_key: str | None = None) -> str:
        body_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
        body_hash = __import__("hashlib").sha256(body_json.encode("utf-8")).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                existing = db.execute("SELECT estimate_id, body_hash FROM estimate_idempotency WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if existing:
                    if existing["body_hash"] != body_hash:
                        raise ValueError("idempotency_key_conflict")
                    return existing["estimate_id"]
            db.execute("INSERT INTO estimates(estimate_id, scenario_id, engine_id, rule_version, status, body_json) VALUES (?, ?, ?, ?, ?, ?)",
                       (estimate_id, result["scenario_id"], result["engine_id"], result["rule_version"], result["status"], body_json))
            if idempotency_key:
                db.execute("INSERT INTO estimate_idempotency(idempotency_key, estimate_id, body_hash) VALUES (?, ?, ?)",
                           (idempotency_key, estimate_id, body_hash))
        return estimate_id

    def get_estimate(self, estimate_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT body_json FROM estimates WHERE estimate_id = ?", (estimate_id,)).fetchone()
            return json.loads(row["body_json"]) if row else None

    def list_estimates(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT estimate_id, body_json, created_at FROM estimates ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
            return [{"estimate_id": row["estimate_id"], "created_at": row["created_at"], **json.loads(row["body_json"])} for row in rows]

    def record_event(self, event_id: str, scenario_id: str, event_type: str, body: dict[str, Any], operation_id: str | None = None) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO observation_events(event_id, scenario_id, operation_id, event_type, body_json) VALUES (?, ?, ?, ?, ?)",
                       (event_id, scenario_id, operation_id, event_type, json.dumps(body, ensure_ascii=False)))

    def events_for(self, scenario_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT event_id, operation_id, event_type, body_json, created_at FROM observation_events WHERE scenario_id = ? ORDER BY created_at, rowid", (scenario_id,)).fetchall()
            return [{"event_id": r[0], "operation_id": r[1], "event_type": r[2], "body": json.loads(r[3]), "created_at": r[4]} for r in rows]

    def save_rule_pack(self, pack: dict[str, Any]) -> None:
        body_json = json.dumps(pack, ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            existing = db.execute("SELECT body_json FROM rule_packs WHERE engine_id = ? AND rule_version = ?", (pack["engine_id"], pack["rule_version"])).fetchone()
            if existing:
                if existing["body_json"] != body_json:
                    raise ValueError("a rule_version is immutable; create a new rule_version for changes")
                return
            db.execute("INSERT INTO rule_packs(engine_id, rule_version, body_json, approved_by, effective_from, status) VALUES (?, ?, ?, ?, ?, ?)",
                       (pack["engine_id"], pack["rule_version"], body_json, pack.get("approved_by"), pack.get("effective_from"), pack.get("status", "unknown")))

    def get_rule_pack(self, engine_id: str, rule_version: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT body_json FROM rule_packs WHERE engine_id = ? AND rule_version = ?", (engine_id, rule_version)).fetchone()
            return json.loads(row[0]) if row else None

    def save_snapshot(self, snapshot_id: str, scenario_id: str, rule_version: str, body: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO offline_snapshots(snapshot_id, scenario_id, rule_version, body_json) VALUES (?, ?, ?, ?)",
                       (snapshot_id, scenario_id, rule_version, json.dumps(body, ensure_ascii=False)))

    def list_pending_snapshots(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body_json FROM offline_snapshots WHERE sync_status = 'pending' ORDER BY created_at")]

    def mark_snapshot_synced(self, snapshot_id: str, server_rule_version: str, accepted: bool) -> str:
        """Only mark sync complete for the same rule version; otherwise preserve a conflict."""
        with self.connect() as db:
            row = db.execute("SELECT rule_version FROM offline_snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
            if not row:
                raise KeyError(snapshot_id)
            if row["rule_version"] != server_rule_version:
                db.execute("UPDATE offline_snapshots SET sync_status = 'version_conflict' WHERE snapshot_id = ?", (snapshot_id,))
                return "version_conflict"
            status = "synced" if accepted else "rejected"
            db.execute("UPDATE offline_snapshots SET sync_status = ? WHERE snapshot_id = ?", (status, snapshot_id))
            return status

    def append_revision(self, revision_id: str, estimate_id: str, supersedes_revision_id: str | None,
                        reason: str, body: dict[str, Any]) -> None:
        """Correct an actual by appending a reasoned revision; never update old evidence."""
        if not reason.strip():
            raise ValueError("revision reason is required")
        with self.connect() as db:
            db.execute("INSERT INTO estimate_revisions(revision_id, estimate_id, supersedes_revision_id, reason, body_json) VALUES (?, ?, ?, ?, ?)",
                       (revision_id, estimate_id, supersedes_revision_id, reason, json.dumps(body, ensure_ascii=False)))

    def list_revisions(self, estimate_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT revision_id, supersedes_revision_id, reason, body_json, created_at FROM estimate_revisions WHERE estimate_id = ? ORDER BY created_at, rowid", (estimate_id,)).fetchall()
            return [{"revision_id": row[0], "supersedes_revision_id": row[1], "reason": row[2], "body": json.loads(row[3]), "created_at": row[4]} for row in rows]
