"""Append-only SQLite proposal, evidence, approval, and effective-rate store."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import ApprovalRequest, Evidence, LaborRate, RateCalculation, RateProposal, RateStatus, RateVersion
from .shared import calculate


def database_path() -> Path:
    return Path(os.environ.get("AUTO_REPAIR_RATE_DB", Path(__file__).resolve().parent.parent / "rate_history.sqlite3"))


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS proposals (
        proposal_id TEXT PRIMARY KEY, module_id TEXT NOT NULL, payload_json TEXT NOT NULL,
        calculation_json TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL,
        evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
        rate_scope TEXT NOT NULL DEFAULT 'factory_standard', rate_type TEXT NOT NULL DEFAULT 'customer'
      );
      CREATE TABLE IF NOT EXISTS approvals (
        approval_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id),
        approved_yen_per_person_hour REAL NOT NULL, effective_from TEXT NOT NULL,
        approved_by TEXT NOT NULL, approval_reason TEXT NOT NULL, approved_at TEXT NOT NULL,
        rate_scope TEXT NOT NULL DEFAULT 'factory_standard', rate_type TEXT NOT NULL DEFAULT 'customer'
      );
      CREATE TABLE IF NOT EXISTS labor_rate_history (
        rate_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id),
        yen_per_person_hour REAL NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT,
        basis_json TEXT NOT NULL, approval_id TEXT NOT NULL REFERENCES approvals(approval_id),
        created_at TEXT NOT NULL, rate_scope TEXT NOT NULL DEFAULT 'factory_standard',
        rate_type TEXT NOT NULL DEFAULT 'customer'
      );
    """)
    # Additive migration for databases created before scoped rates existed.
    # Existing versions remain factory-standard customer prices by default.
    for table in ("proposals", "approvals", "labor_rate_history"):
        existing_columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if "rate_scope" not in existing_columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN rate_scope TEXT NOT NULL DEFAULT 'factory_standard'")
        if "rate_type" not in existing_columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN rate_type TEXT NOT NULL DEFAULT 'customer'")
    db.execute("CREATE INDEX IF NOT EXISTS idx_rate_scope_effective ON labor_rate_history(rate_scope, rate_type, effective_from, effective_to)")
    db.commit()
    return db


def _json(model) -> str:
    return model.model_dump_json()


_RATE_SCOPE_PATTERNS = (
    re.compile(r"category:[\w.-]+", re.UNICODE),
    re.compile(r"season:[\w.-]+", re.UNICODE),
    re.compile(r"customer:[\w.-]+", re.UNICODE),
    re.compile(r"worker:[\w.-]+", re.UNICODE),
)


def _validate_rate_scope(rate_scope: str) -> str:
    normalized_scope = rate_scope.strip()
    if normalized_scope != "factory_standard" and not any(pattern.fullmatch(normalized_scope) for pattern in _RATE_SCOPE_PATTERNS):
        raise ValueError("rate_scope must be factory_standard or an approved typed scope")
    return normalized_scope


def create_proposal(proposal: RateProposal, module_calculation: RateCalculation | None = None, *,
                    rate_scope: str = "factory_standard", rate_type: str = "customer") -> RateVersion:
    """Persist a shared proposal, optionally with a module's shared-contract result."""
    rate_scope = _validate_rate_scope(rate_scope)
    if rate_type not in {"customer", "internal"}:
        raise ValueError("rate_scope and a supported rate_type are required")
    calc = module_calculation or calculate(proposal)
    if calc.status == RateStatus.approved:
        raise ValueError("module calculations cannot issue approved labor_rate values")
    proposal_id = proposal.proposal_id or str(uuid4())
    now = datetime.now(timezone.utc)
    try:
        with connect() as db:
            db.execute("INSERT INTO proposals(proposal_id,module_id,payload_json,calculation_json,status,source,evidence_json,created_at,rate_scope,rate_type) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (proposal_id, proposal.module_id, _json(proposal), _json(calc), calc.status.value,
                        proposal.source, json.dumps([x.model_dump(mode="json") for x in proposal.evidence]), now.isoformat(),
                        rate_scope, rate_type))
    except sqlite3.IntegrityError as exc:
        raise ValueError("proposal_id already exists") from exc
    return RateVersion(proposal_id=proposal_id, module_id=proposal.module_id, rate_scope=rate_scope,
                       rate_type=rate_type, status=calc.status, calculation=calc,
                       source=proposal.source, evidence=proposal.evidence, created_at=now)


def get_proposal(proposal_id: str) -> RateVersion | None:
    with connect() as db:
        row = db.execute("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        approval = db.execute("SELECT * FROM approvals WHERE proposal_id=? ORDER BY approved_at DESC LIMIT 1", (proposal_id,)).fetchone()
    if row is None:
        return None
    calc = RateCalculation.model_validate_json(row["calculation_json"])
    labor_rate = None
    if approval:
        labor_rate = LaborRate(yen_per_person_hour=approval["approved_yen_per_person_hour"],
                               effective_from=date.fromisoformat(approval["effective_from"]), basis=calc.basis)
    evidence = [Evidence.model_validate(item) for item in json.loads(row["evidence_json"])]
    return RateVersion(proposal_id=proposal_id, module_id=row["module_id"], rate_scope=row["rate_scope"],
                       rate_type=row["rate_type"], status=RateStatus(row["status"]), calculation=calc,
                       labor_rate=labor_rate, source=row["source"], evidence=evidence,
                       approved_by=approval["approved_by"] if approval else None,
                       approval_reason=approval["approval_reason"] if approval else None,
                       created_at=datetime.fromisoformat(row["created_at"]))


def approve(proposal_id: str, request: ApprovalRequest) -> RateVersion | None:
    now = datetime.now(timezone.utc)
    approval_id = str(uuid4())
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        if row is None:
            return None
        if row["status"] != RateStatus.draft.value:
            raise ValueError("only an unapproved candidate can be approved")
        if row["rate_type"] != "customer":
            raise ValueError("internal rates cannot be issued as customer labor_rate values")
        calc = RateCalculation.model_validate_json(row["calculation_json"])
        if calc.candidate_yen_per_person_hour is None:
            raise ValueError("blocked proposals cannot be approved")
        latest = db.execute("SELECT MAX(effective_from) AS latest FROM labor_rate_history WHERE rate_scope=? AND rate_type='customer'",
                            (row["rate_scope"],)).fetchone()["latest"]
        if latest is not None and request.effective_from.isoformat() <= latest:
            raise ValueError("effective date overlaps or backdates an existing rate; choose a later date")
        db.execute("INSERT INTO approvals(approval_id,proposal_id,approved_yen_per_person_hour,effective_from,approved_by,approval_reason,approved_at,rate_scope,rate_type) VALUES(?,?,?,?,?,?,?,?,?)",
                   (approval_id, proposal_id, request.approved_yen_per_person_hour,
                    request.effective_from.isoformat(), request.approved_by, request.approval_reason, now.isoformat(),
                    row["rate_scope"], row["rate_type"]))
        db.execute("INSERT INTO labor_rate_history(rate_id,proposal_id,yen_per_person_hour,effective_from,effective_to,basis_json,approval_id,created_at,rate_scope,rate_type) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (str(uuid4()), proposal_id, request.approved_yen_per_person_hour,
                    request.effective_from.isoformat(), None, json.dumps([row.model_dump() for row in calc.basis]), approval_id,
                    now.isoformat(), row["rate_scope"], row["rate_type"]))
        db.execute("UPDATE proposals SET status=? WHERE proposal_id=?", (RateStatus.approved.value, proposal_id))
    return get_proposal(proposal_id)


def list_rates(rate_scope: str | None = None, rate_type: str | None = None) -> list[dict]:
    clauses, params = [], []
    if rate_scope is not None:
        clauses.append("h.rate_scope=?"); params.append(rate_scope)
    if rate_type is not None:
        clauses.append("h.rate_type=?"); params.append(rate_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as db:
        rows = db.execute(f"""
          SELECT h.*, a.approved_by, a.approval_reason
          FROM labor_rate_history h
          JOIN approvals a ON a.approval_id=h.approval_id
          {where}
          ORDER BY h.effective_from DESC, h.created_at DESC
        """, params).fetchall()
    latest_by_scope: dict[tuple[str, str], str] = {}
    result = []
    for r in rows:
        key = (r["rate_scope"], r["rate_type"])
        effective_to = latest_by_scope.get(key)
        latest_by_scope[key] = r["effective_from"]
        result.append(dict(rate_id=r["rate_id"], proposal_id=r["proposal_id"],
                 rate_scope=r["rate_scope"], rate_type=r["rate_type"],
                 labor_rate={"yen_per_person_hour": r["yen_per_person_hour"],
                             "effective_from": r["effective_from"], "basis": json.loads(r["basis_json"])},
                 effective_to=effective_to,
                 approval_id=r["approval_id"], approved_by=r["approved_by"],
                 approval_reason=r["approval_reason"], created_at=r["created_at"]))
    return result


def get_rate_as_of(as_of: date, *, rate_scope: str = "factory_standard", rate_type: str = "customer") -> dict | None:
    """Return one approved rate valid on the requested day, constrained to a scope/type."""
    rate_scope = _validate_rate_scope(rate_scope)
    if rate_type != "customer":
        return None
    with connect() as db:
        row = db.execute("""
          SELECT h.*, a.approved_by, a.approval_reason
          FROM labor_rate_history h JOIN approvals a ON a.approval_id=h.approval_id
          WHERE h.rate_scope=? AND h.rate_type='customer' AND h.effective_from<=?
          ORDER BY h.effective_from DESC LIMIT 1
        """, (rate_scope, as_of.isoformat())).fetchone()
        if row is not None:
            next_effective = db.execute("""
              SELECT MIN(effective_from) FROM labor_rate_history
              WHERE rate_scope=? AND rate_type='customer' AND effective_from>?
            """, (rate_scope, row["effective_from"])).fetchone()[0]
        else:
            next_effective = None
    if row is None:
        return None
    return dict(rate_id=row["rate_id"], proposal_id=row["proposal_id"], rate_scope=row["rate_scope"],
                rate_type=row["rate_type"],
                labor_rate={"yen_per_person_hour": row["yen_per_person_hour"],
                            "effective_from": row["effective_from"], "basis": json.loads(row["basis_json"])},
                effective_to=next_effective, approval_id=row["approval_id"],
                approved_by=row["approved_by"], approval_reason=row["approval_reason"], created_at=row["created_at"])


def list_proposals(limit: int = 30) -> list[RateVersion]:
    """Return recent saved candidates with their calculation and evidence records."""
    bounded_limit = max(1, min(int(limit), 100))
    with connect() as db:
        rows = db.execute("SELECT proposal_id FROM proposals ORDER BY created_at DESC LIMIT ?",
                          (bounded_limit,)).fetchall()
    return [version for row in rows if (version := get_proposal(row["proposal_id"])) is not None]
