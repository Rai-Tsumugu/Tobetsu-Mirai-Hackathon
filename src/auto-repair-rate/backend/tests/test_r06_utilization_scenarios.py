"""R06 scenario formula, input gating, job basis, and shared approval tests."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.r06_utilization_scenarios import calculate_utilization_scenarios

FIXTURE = Path(__file__).parents[2] / "fixtures" / "r06_utilization_scenarios.json"


def fixture_data(**changes):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.pop("fictional_fixture")
    data.update(changes)
    return data


def test_exact_formulas_keep_cost_and_period_hours_fixed_and_order_rates():
    result = calculate_utilization_scenarios(
        allocable_cost_yen=7_200_000, period_total_person_hours=1_600,
        u_period_low=.65, u_period_mid=.75, u_period_high=.85,
        selected_scenario="typical",
    )
    assert result["scenario_rates"]["low"] == pytest.approx(5294.117647)
    assert result["scenario_rates"]["typical"] == pytest.approx(6000)
    assert result["scenario_rates"]["high"] == pytest.approx(6923.076923)
    assert result["candidate_yen_per_person_hour"] == pytest.approx(6000)
    assert result["scenario_denominators"] == pytest.approx({"low": 1360, "typical": 1200, "high": 1040})


@pytest.mark.parametrize("field,value", [
    ("u_period_low", None), ("u_period_mid", None), ("u_period_high", None),
    ("u_period_low", 0), ("u_period_mid", 1.01),
    ("period_total_person_hours", 0), ("allocable_cost_yen", None),
    ("selected_scenario", None),
])
def test_unknown_or_zero_inputs_stop_candidate(field, value):
    data = dict(allocable_cost_yen=1000, period_total_person_hours=10,
                u_period_low=.5, u_period_mid=.6, u_period_high=.7,
                selected_scenario="typical")
    data[field] = value
    assert calculate_utilization_scenarios(**data)["candidate_yen_per_person_hour"] is None


def test_out_of_order_utilization_stops_candidate():
    result = calculate_utilization_scenarios(
        allocable_cost_yen=1000, period_total_person_hours=10,
        u_period_low=.8, u_period_mid=.6, u_period_high=.7,
        selected_scenario="typical",
    )
    assert result["candidate_yen_per_person_hour"] is None
    assert any("low <= mid <= high" in issue for issue in result["blockers"])


def test_r06_persists_selected_candidate_but_waits_for_human_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r06.sqlite3"))
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R06/proposals", json=fixture_data())
        assert response.status_code == 200, response.text
        proposal = response.json()
        assert proposal["status"] == "draft"
        assert proposal["calculation"]["candidate_yen_per_person_hour"] == pytest.approx(6000)
        assert proposal["calculation"]["denominator_person_hours"] == pytest.approx(1200)
        assert proposal["calculation"]["job_billable_person_hours"]["typical"] == pytest.approx(1.2)
        assert proposal["calculation"]["excluded_items"][0]["included_in_labor_pool"] is False
        assert proposal["labor_rate"] is None
        assert client.get("/api/auto-repair-rate/labor-rates").json() == []

        persisted = client.get(f"/api/auto-repair-rate/R06/proposals/{proposal['proposal_id']}").json()
        basis = persisted["calculation"]["basis"]
        values = {item["label"]: item["value"] for item in basis}
        assert values["選択シナリオ"] == "typical"
        assert values["low シナリオ単価"] == pytest.approx(7200000 / (1600 * .85))
        assert values["typical シナリオ単価"] == pytest.approx(6000)
        assert values["high シナリオ単価"] == pytest.approx(7200000 / (1600 * .65))
        assert values["期間分母への案件比率適用"] == "なし"
        assert values["単価適用開始日"] == "2026-11-01"
        assert persisted["evidence"][1]["status"] == "assumed"
        assert persisted["evidence"][1]["source"] == "架空シミュレータ入力"
        assert "説明用の架空稼働率" in persisted["evidence"][1]["notes"]

        blocked = client.post("/api/auto-repair-rate/R06/proposals", json=fixture_data(u_period_mid=None))
        assert blocked.status_code == 200
        assert blocked.json()["status"] == "blocked"
        assert blocked.json()["calculation"]["candidate_yen_per_person_hour"] is None
        assert client.post(f"/api/auto-repair-rate/proposals/{blocked.json()['proposal_id']}/approval", json={
            "approved_yen_per_person_hour": 6000, "effective_from": "2026-12-01",
            "approved_by": "架空", "approval_reason": "架空",
        }).status_code == 409

        approved = client.post(f"/api/auto-repair-rate/proposals/{proposal['proposal_id']}/approval", json={
            "approved_yen_per_person_hour": 6000, "effective_from": "2026-11-01",
            "approved_by": "確認者", "approval_reason": "選択した標準シナリオを確認",
        })
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert client.get("/api/auto-repair-rate/labor-rates").json()[0]["labor_rate"]["yen_per_person_hour"] == 6000


def test_preview_returns_all_scenarios_before_selection_without_saving(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r06_preview.sqlite3"))
    with TestClient(app) as client:
        preview = client.post("/api/auto-repair-rate/R06/scenarios/preview", json=fixture_data(
            selected_scenario=None,
        ))
        assert preview.status_code == 200, preview.text
        data = preview.json()
        assert data["available"] is True
        assert data["scenario_rates"]["typical"] == pytest.approx(6000)
        assert set(data["scenario_rates"]) == {"low", "typical", "high"}
        assert client.get("/api/auto-repair-rate/proposals").json() == []


def test_total_job_basis_requires_ratio_and_applies_it_once_only_to_job(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r06_job.sqlite3"))
    with TestClient(app) as client:
        body = fixture_data(job_billable_ratio=None)
        blocked = client.post("/api/auto-repair-rate/R06/proposals", json=body).json()
        assert blocked["status"] == "blocked"
        assert blocked["calculation"]["candidate_yen_per_person_hour"] is None
        body["job_person_hours"] = None
        no_job = client.post("/api/auto-repair-rate/R06/proposals", json=body).json()
        assert no_job["status"] == "draft"
        assert no_job["calculation"]["denominator_person_hours"] == pytest.approx(1200)


def test_missing_cost_or_scenario_evidence_blocks_even_if_arithmetic_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r06_evidence.sqlite3"))
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R06/proposals", json=fixture_data(scenario_evidence=" "))
        assert response.status_code == 200
        assert response.json()["status"] == "blocked"
        assert response.json()["calculation"]["candidate_yen_per_person_hour"] is None


def test_api_rejects_nonfinite_numeric_input():
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R06/proposals", content=json.dumps({
            **fixture_data(u_period_mid=float("inf")),
        }), headers={"content-type": "application/json"})
    assert response.status_code == 422
