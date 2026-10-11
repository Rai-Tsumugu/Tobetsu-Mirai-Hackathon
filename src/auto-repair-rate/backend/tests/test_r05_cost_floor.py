"""R05 selected profit target, denominator, evidence, and shared-store tests."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.r05_cost_floor import calculate_cost_floor

FIXTURE = Path(__file__).parents[2] / "fixtures" / "r05_cost_floor.json"


def fixture_data(**changes):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.pop("fictional_fixture")
    data.update(changes)
    return data


def test_amount_target_and_period_denominator():
    result = calculate_cost_floor(allocable_cost_yen=5400000, period_total_person_hours=1500,
                                  u_period=.75, target_type="profit_amount", target_value=1350000)
    assert result["cost_rate"] == pytest.approx(4800)
    assert result["denominator_person_hours"] == pytest.approx(1125)
    assert result["candidate_yen_per_person_hour"] == pytest.approx(6000)


def test_margin_target_uses_its_own_formula():
    result = calculate_cost_floor(allocable_cost_yen=5400000, period_total_person_hours=1500,
                                  u_period=.75, target_type="profit_margin", target_value=.2)
    assert result["candidate_yen_per_person_hour"] == pytest.approx(6000)
    assert "1 - target_profit_margin" in result["formula"]


@pytest.mark.parametrize("field,value", [("period_total_person_hours", 0), ("period_total_person_hours", None),
                                           ("u_period", 0), ("u_period", None), ("allocable_cost_yen", None),
                                           ("target_value", None), ("target_type", "both")])
def test_unknown_or_zero_required_input_blocks(field, value):
    data = dict(allocable_cost_yen=1000, period_total_person_hours=10, u_period=.5,
                target_type="profit_amount", target_value=100)
    data[field] = value
    assert calculate_cost_floor(**data)["candidate_yen_per_person_hour"] is None


def test_margin_of_one_blocks():
    result = calculate_cost_floor(allocable_cost_yen=1000, period_total_person_hours=10,
                                  u_period=.5, target_type="profit_margin", target_value=1)
    assert not result["available"]


def test_r05_persists_candidate_material_exclusion_and_job_ratio_only_for_job(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r05.sqlite3"))
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R05/proposals", json=fixture_data())
        assert response.status_code == 200, response.text
        version = response.json()
        assert version["status"] == "draft"
        assert version["calculation"]["candidate_yen_per_person_hour"] == pytest.approx(6000)
        assert version["calculation"]["denominator_person_hours"] == pytest.approx(1125)
        assert version["calculation"]["job_billable_person_hours"]["typical"] == pytest.approx(1.2)
        assert version["calculation"]["excluded_items"][0]["amount_yen"] == 300000
        assert version["labor_rate"] is None
        assert client.get("/api/auto-repair-rate/labor-rates").json() == []
        blocked = client.post("/api/auto-repair-rate/R05/proposals", json=fixture_data(target_evidence=None))
        assert blocked.status_code == 200
        assert blocked.json()["status"] == "blocked"
        assert blocked.json()["calculation"]["candidate_yen_per_person_hour"] is None
        whitespace = client.post("/api/auto-repair-rate/R05/proposals", json=fixture_data(
            cost_evidence="  \t", target_evidence="架空の目標"))
        assert whitespace.status_code == 200
        assert whitespace.json()["status"] == "blocked"
        assert whitespace.json()["evidence"][0]["status"] == "unknown"
        assert client.post(f"/api/auto-repair-rate/proposals/{version['proposal_id']}/approval", json={
            "approved_yen_per_person_hour": 6000, "effective_from": "2026-11-01",
            "approved_by": "架空", "approval_reason": "架空",
        }).status_code == 200
        assert len(client.get("/api/auto-repair-rate/labor-rates").json()) == 1


def test_api_rejects_nonfinite_numeric_input():
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R05/proposals", content=json.dumps({
            **fixture_data(allocable_cost_yen=float("nan")),
        }), headers={"content-type": "application/json"})
    assert response.status_code == 422
