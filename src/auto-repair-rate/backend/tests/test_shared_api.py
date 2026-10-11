"""Shared API and SQLite history contract tests using fictional fixtures."""
from datetime import datetime, timezone
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend import store
from backend.models import RateProposal


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "test.sqlite3"))
    with TestClient(app) as test_client:
        yield test_client


def payload(proposal_id, **changes):
    proposal = {
        "proposal_id": proposal_id, "module_id": "R15",
        "period_start": "2026-01-01", "period_end": "2026-12-31",
        "effective_from": "2026-01-01", "allocable_cost_yen": 7200000,
        "period_total_person_hours": 1600, "u_period": 0.75,
        "hours_basis": "total_person_hours",
        "job_person_hours": {"low": 1, "typical": 1.5, "high": 2.5},
        "job_billable_ratio": 0.8, "costs": [],
        "evidence": [{"label": "fixture", "value": 7200000, "unit": "円/年",
                      "status": "assumed", "source": "fictional_fixture", "evidence_ref": None,
                      "recorded_at": datetime(2026, 10, 11, tzinfo=timezone.utc).isoformat(),
                      "notes": "実データではない"}],
        "source": "fictional_test_fixture", "notes": "架空値のテスト",
    }
    proposal.update(changes)
    return {"proposal": proposal}


def approval(effective_from):
    return {"approved_yen_per_person_hour": 6000, "effective_from": effective_from,
            "approved_by": "架空の確認者", "approval_reason": "テスト用の明示承認"}


def test_period_denominator_is_independent_of_job_ratio_and_approval_shape_is_exact(client):
    result = client.post("/api/auto-repair-rate/proposals", json=payload("one")).json()
    assert result["calculation"]["denominator_person_hours"] == 1200
    assert result["calculation"]["candidate_yen_per_person_hour"] == 6000
    job_hours = result["calculation"]["job_billable_person_hours"]
    assert [job_hours[key] for key in ("low", "typical", "high")] == pytest.approx([0.8, 1.2, 2.0])
    assert result["labor_rate"] is None
    approved = client.post("/api/auto-repair-rate/proposals/one/approval", json=approval("2026-11-01")).json()
    assert set(approved["labor_rate"]) == {"yen_per_person_hour", "effective_from", "basis"}
    assert all(set(row) == {"label", "value", "unit"} for row in approved["labor_rate"]["basis"])
    history = client.get("/api/auto-repair-rate/labor-rates").json()
    assert history[0]["approved_by"] == "架空の確認者"
    assert history[0]["approval_reason"] == "テスト用の明示承認"
    assert history[0]["labor_rate"]["basis"] == approved["labor_rate"]["basis"]


def test_shared_records_api_exposes_recent_candidate_evidence_and_human_titles(client):
    created = client.post("/api/auto-repair-rate/proposals", json=payload("recent-evidence")).json()
    saved = client.get("/api/auto-repair-rate/proposals?limit=5").json()
    recent = next(row for row in saved if row["proposal_id"] == "recent-evidence")
    assert recent["evidence"][0]["source"] == "fictional_fixture"
    assert recent["evidence"][0]["recorded_at"].startswith("2026-10-11")
    assert recent["evidence"][0]["notes"] == "実データではない"
    assert recent["calculation"]["candidate_yen_per_person_hour"] == created["calculation"]["candidate_yen_per_person_hour"]
    modules = {row["module_id"]: row for row in client.get("/api/auto-repair-rate/modules").json()}
    assert modules["R01"]["title"] == "年間原価積上げ単価"
    module_ids = [row["module_id"] for row in client.get("/api/auto-repair-rate/modules").json()]
    assert len(module_ids) == len(set(module_ids))


def test_generic_calculation_endpoint_rejects_other_module_ids(client):
    r04_payload = payload("cannot-bypass-r04", module_id="R04")
    response = client.post("/api/auto-repair-rate/proposals", json=r04_payload)
    assert response.status_code == 422
    assert "dedicated" in response.text
    assert client.get("/api/auto-repair-rate/proposals?limit=10").json() == []


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_shared_proposal_boundary_rejects_non_finite_numbers(client, non_finite):
    body = json.dumps(payload(f"non-finite-{str(non_finite)}", period_total_person_hours=non_finite),
                      allow_nan=True)
    response = client.post("/api/auto-repair-rate/proposals", content=body,
                           headers={"content-type": "application/json"})
    assert response.status_code == 422


def test_billable_job_basis_passes_through_and_missing_basis_blocks_only_job_result(client):
    data = payload("already-billable")["proposal"]
    data["hours_basis"] = "billable_person_hours"
    data["job_billable_ratio"] = 0.2
    result = client.post("/api/auto-repair-rate/proposals", json={"proposal": data}).json()
    assert result["calculation"]["job_billable_person_hours"] == data["job_person_hours"]
    data["proposal_id"] = "missing-job-basis"
    data["hours_basis"] = None
    data["job_billable_ratio"] = None
    result = client.post("/api/auto-repair-rate/proposals", json={"proposal": data}).json()
    assert result["calculation"]["candidate_yen_per_person_hour"] == 6000
    assert result["calculation"]["job_billable_person_hours"] is None
    assert result["calculation"]["job_unknowns"] == ["hours_basis"]


@pytest.mark.parametrize("hours,u_period", [(0, 0.75), (1600, 0), (None, 0.75)])
def test_missing_or_zero_required_period_denominator_blocks_rate(client, hours, u_period):
    result = client.post("/api/auto-repair-rate/proposals", json=payload(
        f"blocked-{hours}-{u_period}", period_total_person_hours=hours, u_period=u_period)).json()
    assert result["status"] == "blocked"
    assert result["calculation"]["candidate_yen_per_person_hour"] is None
    assert result["labor_rate"] is None


def test_duplicate_proposal_repeat_approval_and_overlap_conflict(client):
    path = "/api/auto-repair-rate/proposals"
    assert client.post(path, json=payload("duplicate")).status_code == 200
    assert client.post(path, json=payload("duplicate")).status_code == 409
    assert client.post(f"{path}/duplicate/approval", json=approval("2026-10-01")).status_code == 200
    assert client.post(f"{path}/duplicate/approval", json=approval("2026-12-01")).status_code == 409
    assert client.post(path, json=payload("second")).status_code == 200
    assert client.post(f"{path}/second/approval", json=approval("2026-10-01")).status_code == 409
    assert client.post(f"{path}/second/approval", json=approval("2026-12-01")).status_code == 200
    history = client.get("/api/auto-repair-rate/labor-rates").json()
    assert len(history) == 2
    assert next(row for row in history if row["proposal_id"] == "duplicate")["effective_to"] == "2026-12-01"


def test_separately_billed_material_cannot_be_included_in_labor_pool(client):
    data = payload("bad-material")["proposal"]
    data["costs"] = [{"cost_id": "paint", "label": "架空塗料", "amount_yen": 1000,
                      "period": "2026", "source": "fixture", "evidence_status": "assumed",
                      "billing_class": "separately_billed_item", "included_in_labor_pool": True}]
    assert client.post("/api/auto-repair-rate/proposals", json={"proposal": data}).status_code == 422


def test_rate_scopes_keep_category_approvals_independent_and_active_is_factory_only(client):
    old_factory = store.create_proposal(RateProposal.model_validate(payload("scope-factory-old")["proposal"]))
    old_factory_approval = client.post(
        f"/api/auto-repair-rate/proposals/{old_factory.proposal_id}/approval",
        json={**approval("2026-10-01"), "approved_yen_per_person_hour": 5500})
    assert old_factory_approval.status_code == 200, old_factory_approval.text
    for scope, proposal_id, amount in [
        ("category:repair", "scope-repair", 6100),
        ("category:paint", "scope-paint", 7200),
        ("factory_standard", "scope-factory", 6000),
    ]:
        base = payload(proposal_id)["proposal"]
        base["allocable_cost_yen"] = amount
        saved = store.create_proposal(RateProposal.model_validate(base), rate_scope=scope)
        response = client.post(f"/api/auto-repair-rate/proposals/{saved.proposal_id}/approval",
                               json=approval("2026-11-01"))
        assert response.status_code == 200, response.text
    all_rates = client.get("/api/auto-repair-rate/labor-rates").json()
    assert {(rate["rate_scope"], rate["labor_rate"]["effective_from"]) for rate in all_rates} == {
        ("factory_standard", "2026-10-01"),
        ("category:repair", "2026-11-01"), ("category:paint", "2026-11-01"), ("factory_standard", "2026-11-01")}
    for scope in {rate["rate_scope"] for rate in all_rates} - {"factory_standard"}:
        scoped = client.get("/api/auto-repair-rate/labor-rates", params={"rate_scope": scope}).json()
        assert len(scoped) == 1
        assert scoped[0]["effective_to"] is None
    factory_history = client.get("/api/auto-repair-rate/labor-rates", params={"rate_scope": "factory_standard"}).json()
    assert len(factory_history) == 2
    assert next(row for row in factory_history if row["labor_rate"]["effective_from"] == "2026-10-01")["effective_to"] == "2026-11-01"
    active_prior = client.get("/api/auto-repair-rate/labor-rates/active", params={"as_of": "2026-10-15"}).json()
    assert active_prior["labor_rate"]["yen_per_person_hour"] == 5500
    active = client.get("/api/auto-repair-rate/labor-rates/active", params={"as_of": "2026-11-01"}).json()
    assert active["rate_scope"] == "factory_standard"
    assert active["rate_type"] == "customer"
    assert active["labor_rate"]["yen_per_person_hour"] == 6000


def test_internal_rate_cannot_create_customer_labor_rate(client):
    saved = store.create_proposal(RateProposal.model_validate(payload("internal-only")["proposal"]),
                                  rate_scope="worker:fictional-01", rate_type="internal")
    response = client.post(f"/api/auto-repair-rate/proposals/{saved.proposal_id}/approval",
                           json=approval("2026-11-01"))
    assert response.status_code == 409
    assert "internal rates" in response.text
    assert client.get("/api/auto-repair-rate/labor-rates").json() == []


def test_old_unscoped_database_migrates_without_losing_rows(tmp_path, monkeypatch):
    import sqlite3

    database = tmp_path / "old-rate-history.sqlite3"
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(database))
    with sqlite3.connect(database) as db:
        db.executescript("""
          CREATE TABLE proposals (
            proposal_id TEXT PRIMARY KEY, module_id TEXT NOT NULL, payload_json TEXT NOT NULL,
            calculation_json TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL,
            evidence_json TEXT NOT NULL, created_at TEXT NOT NULL);
          CREATE TABLE approvals (
            approval_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id),
            approved_yen_per_person_hour REAL NOT NULL, effective_from TEXT NOT NULL,
            approved_by TEXT NOT NULL, approval_reason TEXT NOT NULL, approved_at TEXT NOT NULL);
          CREATE TABLE labor_rate_history (
            rate_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id),
            yen_per_person_hour REAL NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT,
            basis_json TEXT NOT NULL, approval_id TEXT NOT NULL REFERENCES approvals(approval_id),
            created_at TEXT NOT NULL);
          INSERT INTO proposals VALUES('legacy','R15','{}','{}','approved','fixture','[]','2026-01-01T00:00:00+00:00');
          INSERT INTO approvals VALUES('legacy-approval','legacy',6000,'2026-01-01','fixture-user','legacy approval','2026-01-01T00:00:00+00:00');
          INSERT INTO labor_rate_history VALUES('legacy-rate','legacy',6000,'2026-01-01',NULL,'[]','legacy-approval','2026-01-01T00:00:00+00:00');
        """)
    with store.connect() as db:
        row = db.execute("SELECT rate_scope, rate_type FROM proposals WHERE proposal_id='legacy'").fetchone()
        assert tuple(row) == ("factory_standard", "customer")
        columns = {item[1] for item in db.execute("PRAGMA table_info(labor_rate_history)")}
        assert {"rate_scope", "rate_type"} <= columns
        assert db.execute("SELECT COUNT(*) FROM proposals WHERE proposal_id='legacy'").fetchone()[0] == 1
    migrated_rate = store.list_rates()[0]
    assert migrated_rate["rate_scope"] == "factory_standard"
    assert migrated_rate["rate_type"] == "customer"


def test_rate_scope_rejects_untyped_or_unsafe_values(client):
    base = RateProposal.model_validate(payload("bad-scope")["proposal"])
    with pytest.raises(ValueError, match="rate_scope"):
        store.create_proposal(base, rate_scope="arbitrary_scope")
