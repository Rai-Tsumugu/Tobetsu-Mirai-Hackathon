"""R04 reference conversion and shared-store isolation tests."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.r04_benchmark_reference import BenchmarkInput, calculate_benchmark

FIXTURE = Path(__file__).parents[2] / "fixtures" / "r04_benchmark_reference.json"


def fixture_data(**updates):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.pop("fictional_fixture")
    data.update(updates)
    return data


def test_labor_only_documented_hours_convert_to_reference_only():
    result = calculate_benchmark(fixture_data())
    assert result.available
    assert result.reference_yen_per_person_hour == pytest.approx(6000)


@pytest.mark.parametrize("changes", [
    {"amount_type": "total"}, {"amount_type": "unknown"},
    {"documented_person_hours": None}, {"documented_person_hours": 0},
    {"permission_status": "unknown"}, {"permission_status": "not_verified"},
    {"currency": "USD"},
])
def test_unclear_scope_hours_permission_or_currency_is_unusable(changes):
    result = calculate_benchmark(fixture_data(**changes))
    assert not result.available
    assert result.reference_yen_per_person_hour is None
    assert result.reason


def test_r04_saves_source_and_effective_context_without_issuing_or_changing_factory_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r04.sqlite3"))
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R04/proposals", json={
            **fixture_data(), "period_start": "2026-01-01", "effective_from": "2026-11-01",
            "job_hours_basis": "total_person_hours", "job_billable_ratio": 0.8,
        })
        assert response.status_code == 200, response.text
        reference = response.json()
        assert reference["status"] == "blocked"
        assert reference["calculation"]["candidate_yen_per_person_hour"] is None
        assert reference["labor_rate"] is None
        basis = reference["calculation"]["basis"]
        assert next(row for row in basis if row["label"] == "外部参照値")["value"] == 6000
        assert next(row for row in basis if row["label"] == "資料確認日")["value"] == "2026-10-11"
        assert next(row for row in basis if row["label"] == "記録上の適用開始日")["value"] == "2026-11-01"
        assert "total_person_hours" in reference["evidence"][-1]["notes"]
        assert client.get("/api/auto-repair-rate/labor-rates").json() == []
        assert client.post(f"/api/auto-repair-rate/proposals/{reference['proposal_id']}/approval", json={
            "approved_yen_per_person_hour": 6000, "effective_from": "2026-11-01",
            "approved_by": "架空", "approval_reason": "架空",
        }).status_code == 409


def test_endpoint_rejects_client_calculations_and_does_not_fetch_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r04-invalid.sqlite3"))
    with TestClient(app) as client:
        body = {**fixture_data(), "period_start": "2026-01-01", "effective_from": "2026-11-01",
                "candidate_yen_per_person_hour": 1}
        assert client.post("/api/auto-repair-rate/R04/proposals", json=body).status_code == 422


def test_api_rejects_nonfinite_numeric_input():
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R04/proposals", content=json.dumps({
            **fixture_data(amount=float("inf")), "period_start": "2026-01-01",
            "effective_from": "2026-11-01",
        }), headers={"content-type": "application/json"})
    assert response.status_code == 422
