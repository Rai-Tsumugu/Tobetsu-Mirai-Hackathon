"""R03 salary-multiplier math, blocking, API persistence, and approval flow."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.models import CostItem, RateProposal, RateStatus
from backend.r03_salary_multiplier import calculate_salary_multiplier

FIXTURE = Path(__file__).parents[2] / "fixtures" / "r03_salary_multiplier.json"


def fixture_data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fixture_proposal(**updates):
    data = fixture_data()
    proposal = {
        "module_id": "R03", "period_start": "2026-01-01", "period_end": "2026-12-31",
        "effective_from": "2026-11-01", "allocable_cost_yen": None,
        "period_total_person_hours": data["period_total_person_hours"], "u_period": data["u_period"],
        "hours_basis": data["hours_basis"], "job_person_hours": data["job_person_hours"],
        "job_billable_ratio": data["job_billable_ratio"], "costs": [], "evidence": [],
        "source": "fictional_fixture", "notes": data["note"],
    }
    proposal.update(updates)
    return proposal


def calc(**changes):
    data = fixture_data()
    data.update(changes)
    proposal_fields = {key: value for key, value in changes.items() if key in {
        "period_total_person_hours", "u_period", "hours_basis", "job_person_hours", "job_billable_ratio"
    }}
    proposal = RateProposal(**fixture_proposal(**proposal_fields))
    return calculate_salary_multiplier(
        proposal, data["daily_pay_yen"], data["paid_days_per_year"],
        data["approved_multiplier"], data["multiplier_approved_by"],
        data["salary_basis_acknowledged"],
    )


def test_formula_is_period_salary_times_multiplier_over_billable_period_hours():
    result = calc()
    assert result.status == RateStatus.draft
    assert result.denominator_person_hours == 1200
    assert result.candidate_yen_per_person_hour == pytest.approx(6000)
    assert next(row for row in result.basis if row.label == "年間給与換算額").value == 2_400_000
    assert next(row for row in result.basis if row.label == "工場で承認した給与倍率").value == 3
    assert result.job_billable_person_hours.model_dump() == {"low": 0.8, "typical": 1.2, "high": 2.0}
    assert all("相場" not in str(row.value) for row in result.basis)


@pytest.mark.parametrize("changes, blocker", [
    ({"paid_days_per_year": None}, "paid_days_per_year_unknown_or_not_finite"),
    ({"period_total_person_hours": 0}, "required_denominator_is_zero"),
    ({"u_period": 0}, "required_denominator_is_zero"),
    ({"period_total_person_hours": None}, "period_total_person_hours_unknown_or_not_finite"),
    ({"u_period": None}, "u_period_unknown_or_not_finite"),
    ({"approved_multiplier": None}, "approved_multiplier_unknown_or_not_finite"),
    ({"multiplier_approved_by": ""}, "multiplier_approval_by_president_required"),
    ({"salary_basis_acknowledged": False}, "salary_multiplier_comparison_acknowledgement_required"),
])
def test_missing_days_denominator_or_approvals_block_candidate(changes, blocker):
    result = calc(**changes)
    assert result.status == RateStatus.blocked
    assert result.candidate_yen_per_person_hour is None
    assert blocker in result.unknowns


def test_job_billable_hours_are_not_scaled_twice_and_ratio_does_not_change_period_rate():
    total = calc()
    changed_proposal = RateProposal(**fixture_proposal(job_billable_ratio=0.2))
    changed_ratio = calculate_salary_multiplier(changed_proposal, 10000, 240, 3, "架空社長", True)
    assert total.candidate_yen_per_person_hour == changed_ratio.candidate_yen_per_person_hour
    assert total.job_billable_person_hours.typical != changed_ratio.job_billable_person_hours.typical
    already_billable = RateProposal(**fixture_proposal(hours_basis="billable_person_hours", job_billable_ratio=0.2))
    result = calculate_salary_multiplier(already_billable, 10000, 240, 3, "架空社長", True)
    assert result.job_billable_person_hours.model_dump() == {"low": 1, "typical": 1.5, "high": 2.5}


def test_separately_billed_materials_are_retained_as_excluded_evidence():
    proposal = RateProposal(**fixture_proposal(costs=[{
        "cost_id": "fictional_materials", "label": "架空の別請求材料",
        "amount_yen": 1200, "period": "架空期間", "source": "fictional_fixture",
        "evidence_status": "assumed", "billing_class": "separately_billed_item",
        "included_in_labor_pool": False, "excluded_reason": "別請求のため除外",
    }]))
    result = calculate_salary_multiplier(proposal, 10000, 240, 3, "架空社長", True)
    assert result.candidate_yen_per_person_hour == pytest.approx(6000)
    assert [item.cost_id for item in result.excluded_items] == ["fictional_materials"]


def test_api_persists_candidate_then_only_shared_approval_issues_labor_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r03.sqlite3"))
    data = fixture_data()
    body = {
        "proposal": fixture_proposal(), "daily_pay_yen": data["daily_pay_yen"],
        "paid_days_per_year": data["paid_days_per_year"], "approved_multiplier": data["approved_multiplier"],
        "multiplier_approved_by": data["multiplier_approved_by"],
        "salary_basis_acknowledged": data["salary_basis_acknowledged"],
    }
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R03/proposals", json=body)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["calculation"]["candidate_yen_per_person_hour"] == pytest.approx(6000)
        assert saved["labor_rate"] is None
        assert saved["evidence"][-1]["value"] == 3
        assert all(item["source"] == "R03 proposal input" for item in saved["evidence"])
        assert all(item["recorded_at"] for item in saved["evidence"])
        assert all(item["status"] in {"entered", "unknown"} for item in saved["evidence"])
        assert saved["evidence"][-1]["notes"]
        assert {row["label"] for row in saved["calculation"]["basis"]} >= {
            "年間給与換算額", "算定分母", "算定方式", "工場で承認した給与倍率"
        }
        fetched = client.get(f"/api/auto-repair-rate/proposals/{saved['proposal_id']}").json()
        assert fetched["calculation"]["candidate_yen_per_person_hour"] == pytest.approx(6000)
        approved = client.post(f"/api/auto-repair-rate/proposals/{saved['proposal_id']}/approval", json={
            "approved_yen_per_person_hour": 6000, "effective_from": "2026-11-01",
            "approved_by": "架空の最終承認者", "approval_reason": "架空テスト承認",
        })
        rate = approved.json()["labor_rate"]
        assert set(rate) == {"yen_per_person_hour", "effective_from", "basis"}
        assert rate["yen_per_person_hour"] == 6000
        assert client.get("/api/auto-repair-rate/labor-rates").json()[0]["labor_rate"] == rate


def test_blocked_api_result_is_saved_and_client_cannot_submit_calculation(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r03-blocked.sqlite3"))
    body = {"proposal": fixture_proposal(period_total_person_hours=0), "daily_pay_yen": 10000,
            "paid_days_per_year": None, "approved_multiplier": 3, "multiplier_approved_by": "",
            "salary_basis_acknowledged": False}
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R03/proposals", json=body)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["status"] == "blocked"
        assert saved["calculation"]["candidate_yen_per_person_hour"] is None
        assert client.get(f"/api/auto-repair-rate/proposals/{saved['proposal_id']}").status_code == 200
        body["candidate_yen_per_person_hour"] = 1
        assert client.post("/api/auto-repair-rate/R03/proposals", json=body).status_code == 422


def test_api_rejects_nonfinite_numeric_input():
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R03/proposals", content=json.dumps({
            "proposal": fixture_proposal(), "daily_pay_yen": float("nan"),
        }), headers={"content-type": "application/json"})
    assert response.status_code == 422
