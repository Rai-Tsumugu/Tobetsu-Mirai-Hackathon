"""Focused coverage for R07-R10 allocation, evidence, and shared approval gates."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.r07_department_cost_pools import calculate_department_rates
from backend.r08_annual_heating import calculate_annual_heating_rate
from backend.r09_winter_allocation import calculate_winter_scenario
from backend.r10_rolling_smoothing import calculate_rolling_smoothing

FIXTURES = Path(__file__).parents[2] / "fixtures"


def fixture(name, **changes):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    data.pop("fictional_fixture")
    data.update(changes)
    return data


def test_r07_exactly_two_categories_allocate_common_cost_and_reconcile():
    result = calculate_department_rates(direct_cost_yen={"整備": 800000, "鈑金塗装": 500000},
        shared_cost_yen=1000000, allocation_key={"整備": 3, "鈑金塗装": 2},
        total_person_hours={"整備": 1200, "鈑金塗装": 700}, u_period={"整備": .75, "鈑金塗装": .7})
    assert result["allocated_shared_cost_yen"] == {"整備": 600000.0, "鈑金塗装": 400000.0}
    assert result["reconciles"] is True
    assert sum(result["allocated_shared_cost_yen"].values()) == result["source_shared_cost_yen"]
    assert result["rate_yen_per_person_hour"]["整備"] == pytest.approx(1400000 / (1200 * .75))


@pytest.mark.parametrize("value", [None, 0, float("nan")])
def test_r07_missing_zero_or_nonfinite_denominator_stops(value):
    result = calculate_department_rates(direct_cost_yen={"整備": 1, "鈑金塗装": 1}, shared_cost_yen=1,
        allocation_key={"整備": 1, "鈑金塗装": 1}, total_person_hours={"整備": 10, "鈑金塗装": 10},
        u_period={"整備": .5, "鈑金塗装": value})
    assert result["rate_yen_per_person_hour"]["鈑金塗装"] is None
    assert result["available"] is False


def test_r08_uses_same_annual_denominator_and_stops_zero_or_unknown_hours():
    result = calculate_annual_heating_rate(annual_heating_cost_yen=600000, other_allocable_cost_yen=6600000, annual_billable_hours=1200)
    assert result["annual_heating_rate"] == pytest.approx(500)
    assert result["annual_base_rate"] == pytest.approx(5500)
    assert result["candidate_yen_per_person_hour"] == pytest.approx(6000)
    for hours in (None, 0, float("inf")):
        assert calculate_annual_heating_rate(annual_heating_cost_yen=1, other_allocable_cost_yen=1,
                                             annual_billable_hours=hours)["candidate_yen_per_person_hour"] is None


def test_r09_winter_scenario_requires_winter_hours_and_policy_confirmation():
    params = dict(winter_cost_yen=300000, winter_billable_hours=240, annual_baseline_rate=6000,
                  annual_billable_hours=1200)
    result = calculate_winter_scenario(**params, price_policy_confirmed=True)
    assert result["winter_candidate_rate"] == pytest.approx(7250)
    assert result["delta_yen_per_person_hour"] == pytest.approx(1250)
    assert result["annual_impact_yen"] == pytest.approx(300000)
    assert result["applied_by_default"] is False
    assert calculate_winter_scenario(**{**params, "winter_billable_hours": 0}, price_policy_confirmed=True)["winter_candidate_rate"] is None
    assert "冬季価格方針を確認してください" in calculate_winter_scenario(**params, price_policy_confirmed=False)["blockers"]


def test_r10_uses_aggregate_weighted_rate_and_blocks_missing_month_or_double_count():
    costs = [100] * 11 + [300]
    hours = [100] * 11 + [200]
    ratios = [.5] * 12
    result = calculate_rolling_smoothing(monthly_cost_yen=costs, monthly_total_person_hours=hours,
        monthly_u_period=ratios, invoice_month=12, seasonal_allocation_already_applied=False)
    assert result["raw_invoice_month_rate"] == pytest.approx(3)
    assert result["smoothed_rate"] == pytest.approx(1400 / 650)
    incomplete = calculate_rolling_smoothing(monthly_cost_yen=costs[:-1] + [None], monthly_total_person_hours=hours,
        monthly_u_period=ratios, invoice_month=12, seasonal_allocation_already_applied=False)
    assert incomplete["smoothed_rate"] is None
    double_counted = calculate_rolling_smoothing(monthly_cost_yen=costs, monthly_total_person_hours=hours,
        monthly_u_period=ratios, invoice_month=12, seasonal_allocation_already_applied=True)
    assert double_counted["smoothed_rate"] is None


@pytest.mark.parametrize("module,filename,expected_scope", [("R07", "r07_department_cost_pools.json", "category:整備"),
    ("R08", "r08_annual_heating.json", "factory_standard"), ("R09", "r09_winter_allocation.json", "season:winter"),
    ("R10", "r10_rolling_smoothing.json", "factory_standard")])
def test_module_proposal_requires_finite_evidence_and_only_approval_creates_labor_rate(tmp_path, monkeypatch, module, filename, expected_scope):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / f"{module}.sqlite3"))
    with TestClient(app) as client:
        response = client.post(f"/api/auto-repair-rate/{module}/proposals", json=fixture(filename))
        assert response.status_code == 200, response.text
        proposal = response.json()
        assert proposal["status"] == "draft"
        assert proposal["rate_scope"] == expected_scope
        assert proposal["rate_type"] == "customer"
        assert proposal["calculation"]["candidate_yen_per_person_hour"] is not None
        assert proposal["labor_rate"] is None
        assert client.get("/api/auto-repair-rate/labor-rates").json() == []
        assert proposal["evidence"][0]["source"] == "架空シミュレータ"
        assert proposal["evidence"][0]["status"] == "assumed"
        assert proposal["calculation"]["excluded_items"][0]["included_in_labor_pool"] is False
        persisted = client.get(f"/api/auto-repair-rate/{module}/proposals/{proposal['proposal_id']}").json()
        assert persisted["rate_scope"] == expected_scope
        assert persisted["rate_type"] == "customer"
        approval = client.post(f"/api/auto-repair-rate/proposals/{proposal['proposal_id']}/approval", json={
            "approved_yen_per_person_hour": proposal["calculation"]["candidate_yen_per_person_hour"],
            "effective_from": "2026-11-01", "approved_by": "確認者", "approval_reason": "根拠を確認", })
        assert approval.status_code == 200, approval.text
        assert approval.json()["labor_rate"] is not None
        assert approval.json()["rate_scope"] == expected_scope
        assert approval.json()["rate_type"] == "customer"
        history = client.get("/api/auto-repair-rate/labor-rates").json()
        assert len(history) == 1
        assert history[0]["rate_scope"] == expected_scope
        assert history[0]["rate_type"] == "customer"


def test_r09_winter_requires_policy_confirmation_and_r10_missing_capacity_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "gates.sqlite3"))
    with TestClient(app) as client:
        r09 = client.post("/api/auto-repair-rate/R09/proposals", json=fixture("r09_winter_allocation.json", price_policy_confirmed=False))
        assert r09.json()["status"] == "blocked"
        assert r09.json()["labor_rate"] is None
        r10_data = fixture("r10_rolling_smoothing.json")
        r10_data["monthly_total_person_hours"][4] = None
        r10 = client.post("/api/auto-repair-rate/R10/proposals", json=r10_data)
        assert r10.json()["status"] == "blocked"
        assert r10.json()["calculation"]["candidate_yen_per_person_hour"] is None


def test_r09_annual_baseline_can_be_saved_when_winter_hours_are_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r09_baseline.sqlite3"))
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R09/proposals", json=fixture(
            "r09_winter_allocation.json", selected_scenario="annual_baseline",
            winter_billable_hours=None, price_policy_confirmed=False))
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "draft"
        assert response.json()["rate_scope"] == "factory_standard"
        assert response.json()["rate_type"] == "customer"
        assert response.json()["calculation"]["candidate_yen_per_person_hour"] == 6000
        assert response.json()["calculation"]["denominator_person_hours"] == 1200
        assert response.json()["calculation"]["unknowns"] == []
        basis = {row["label"]: row["value"] for row in response.json()["calculation"]["basis"]}
        assert basis["共有候補の配賦費用合計（単価×分母から導出）"] == 6000 * 1200
        assert basis["共有候補の選択案"] == "annual_baseline"


def test_r10_requires_calendar_aligned_twelve_month_period(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r10_period.sqlite3"))
    with TestClient(app) as client:
        data = fixture("r10_rolling_smoothing.json", period_start="2026-01-01", period_end="2026-11-30")
        response = client.post("/api/auto-repair-rate/R10/proposals", json=data)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "blocked"
        assert "月初から月末までの連続12か月" in response.json()["calculation"]["unknowns"][0]


@pytest.mark.parametrize("filename,changes", [
    ("r08_annual_heating.json", {"annual_period_end": "2026-12-30"}),
    ("r08_annual_heating.json", {"annual_period_end": "2027-01-01"}),
    ("r09_winter_allocation.json", {"annual_period_end": "2026-12-30"}),
    ("r09_winter_allocation.json", {"annual_period_end": "2027-01-01"}),
])
def test_r08_r09_reject_nonannual_periods(tmp_path, monkeypatch, filename, changes):
    module = "R08" if filename.startswith("r08") else "R09"
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / f"{module}_{changes['annual_period_end']}.sqlite3"))
    with TestClient(app) as client:
        response = client.post(f"/api/auto-repair-rate/{module}/proposals", json=fixture(filename, **changes))
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "blocked"
        assert response.json()["calculation"]["candidate_yen_per_person_hour"] is None
        assert any("1年間" in item for item in response.json()["calculation"]["unknowns"])


@pytest.mark.parametrize("module,filename", [("R07", "r07_department_cost_pools.json"),
    ("R08", "r08_annual_heating.json"), ("R09", "r09_winter_allocation.json"),
    ("R10", "r10_rolling_smoothing.json")])
def test_api_rejects_nonfinite_values(module, filename):
    data = fixture(filename)
    # JSON's non-standard NaN token is rejected by FiniteModel validation.
    if module == "R07": data["shared_cost_yen"] = float("nan")
    elif module == "R08": data["annual_billable_hours"] = float("inf")
    elif module == "R09": data["winter_billable_hours"] = float("nan")
    else: data["monthly_cost_yen"][0] = float("inf")
    with TestClient(app) as client:
        response = client.post(f"/api/auto-repair-rate/{module}/rates/preview",
                               content=json.dumps(data, allow_nan=True), headers={"Content-Type": "application/json"})
    assert response.status_code == 422
