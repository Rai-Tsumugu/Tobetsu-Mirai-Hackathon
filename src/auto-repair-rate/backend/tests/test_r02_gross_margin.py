"""R02 formula, blocking rules, and shared approval/history integration."""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.models import RateProposal, RateStatus
from backend.r02_gross_margin import calculate_gross_margin

FIXTURE = Path(__file__).parents[2] / "fixtures" / "r02_gross_margin.json"


def fixture_proposal(**updates):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    proposal = {
        "module_id": "R02", "period_start": "2026-01-01", "period_end": "2026-12-31",
        "effective_from": "2026-11-01", "allocable_cost_yen": data["allocable_cost_yen"],
        "period_total_person_hours": data["period_total_person_hours"], "u_period": data["u_period"],
        "hours_basis": data["hours_basis"], "job_person_hours": data["job_person_hours"],
        "job_billable_ratio": data["job_billable_ratio"], "costs": data["costs"],
        "evidence": data["evidence"], "source": "fictional_fixture", "notes": "架空値",
    }
    proposal.update(updates)
    return proposal


def test_gross_margin_formula_is_not_cost_markup_and_materials_are_excluded():
    proposal = RateProposal(**fixture_proposal())
    result = calculate_gross_margin(proposal, 0.2, payroll_nonduplicated=True)
    assert result.status == RateStatus.draft
    assert result.denominator_person_hours == 1200
    assert result.candidate_yen_per_person_hour == pytest.approx(7500)
    assert result.candidate_yen_per_person_hour != pytest.approx(7200)  # markup on cost
    assert [item.cost_id for item in result.excluded_items] == ["fictional_materials"]
    assert next(row for row in result.basis if row.label == "請求可能人時あたり原価").value == 6000


@pytest.mark.parametrize("margin", [-0.01, 1, 1.1, "nan"])
def test_invalid_margins_block_candidate(margin):
    result = calculate_gross_margin(RateProposal(**fixture_proposal()), margin, payroll_nonduplicated=True)
    assert result.status == RateStatus.blocked
    assert result.candidate_yen_per_person_hour is None
    assert any("gross_margin" in blocker for blocker in result.unknowns)


@pytest.mark.parametrize("changes", [
    {"period_total_person_hours": None}, {"period_total_person_hours": 0},
    {"u_period": None}, {"u_period": 0}, {"allocable_cost_yen": None}, {"allocable_cost_yen": 0},
    {"evidence": []},
])
def test_missing_or_zero_denominator_cost_or_evidence_blocks(changes):
    result = calculate_gross_margin(RateProposal(**fixture_proposal(**changes)), 0.2, payroll_nonduplicated=True)
    assert result.status == RateStatus.blocked
    assert result.candidate_yen_per_person_hour is None


def test_job_basis_is_independent_and_billable_hours_pass_through():
    missing_basis = calculate_gross_margin(RateProposal(**fixture_proposal(hours_basis=None, job_billable_ratio=None)), 0.2, payroll_nonduplicated=True)
    assert missing_basis.candidate_yen_per_person_hour == pytest.approx(7500)
    assert missing_basis.job_billable_person_hours is None
    assert missing_basis.job_unknowns == ["hours_basis"]
    already_billable = calculate_gross_margin(RateProposal(**fixture_proposal(hours_basis="billable_person_hours", job_billable_ratio=0.2)), 0.2, payroll_nonduplicated=True)
    assert already_billable.job_billable_person_hours.model_dump() == {"low": 1, "typical": 1.5, "high": 2.5}


def test_payroll_pool_lines_must_reconcile_and_materials_cannot_be_included():
    mismatch = RateProposal(**fixture_proposal(allocable_cost_yen=7200001))
    result = calculate_gross_margin(mismatch, 0.2, payroll_nonduplicated=True)
    assert result.candidate_yen_per_person_hour is None
    assert "allocable_cost_does_not_match_included_cost_items" in result.unknowns
    data = fixture_proposal()
    data["costs"][1]["included_in_labor_pool"] = True
    with pytest.raises(ValueError, match="separately billed"):
        RateProposal(**data)


def test_r02_api_saves_candidate_without_rate_then_approval_creates_history(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r02.sqlite3"))
    with TestClient(app) as client:
        payload = {"proposal": fixture_proposal(), "gross_margin": 0.2, "payroll_nonduplicated": True}
        response = client.post("/api/auto-repair-rate/R02/proposals", json=payload)
        assert response.status_code == 200, response.text
        candidate = response.json()
        assert candidate["calculation"]["candidate_yen_per_person_hour"] == pytest.approx(7500)
        assert candidate["labor_rate"] is None
        assert candidate["evidence"][-1]["label"] == "R02粗利率入力"
        proposal_id = candidate["proposal_id"]
        fetched = client.get(f"/api/auto-repair-rate/proposals/{proposal_id}").json()
        assert fetched["evidence"][-1]["value"] == 0.2
        approved = client.post(f"/api/auto-repair-rate/proposals/{proposal_id}/approval", json={
            "approved_yen_per_person_hour": 7500, "effective_from": "2026-11-01",
            "approved_by": "架空の承認者", "approval_reason": "架空テスト承認",
        })
        assert approved.status_code == 200, approved.text
        rate = approved.json()["labor_rate"]
        assert set(rate) == {"yen_per_person_hour", "effective_from", "basis"}
        assert all(set(row) == {"label", "value", "unit"} for row in rate["basis"])
        assert len(client.get("/api/auto-repair-rate/labor-rates").json()) == 1


def test_r02_endpoint_rejects_client_calculation_and_out_of_range_margin(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r02-invalid.sqlite3"))
    with TestClient(app) as client:
        assert client.post("/api/auto-repair-rate/R02/proposals", json={"proposal": fixture_proposal(), "gross_margin": 1, "payroll_nonduplicated": True}).status_code == 422
        body = {"proposal": fixture_proposal(), "gross_margin": 0.2, "payroll_nonduplicated": True, "candidate_yen_per_person_hour": 1}
        assert client.post("/api/auto-repair-rate/R02/proposals", json=body).status_code == 422


def test_r02_requires_aggregate_cost_evidence_before_adding_margin_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r02-no-cost-evidence.sqlite3"))
    with TestClient(app) as client:
        proposal = fixture_proposal(evidence=[])
        response = client.post("/api/auto-repair-rate/R02/proposals", json={
            "proposal": proposal, "gross_margin": 0.2, "payroll_nonduplicated": True,
        })
    assert response.status_code == 200
    saved = response.json()
    assert saved["calculation"]["candidate_yen_per_person_hour"] is None
    assert "allocable_cost_evidence" in saved["calculation"]["unknowns"]
    assert saved["evidence"][-1]["label"] == "R02粗利率入力"


def test_r02_payroll_nonduplicated_confirmation_is_required(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r02-payroll-confirm.sqlite3"))
    with TestClient(app) as client:
        payload = {"proposal": fixture_proposal(), "gross_margin": 0.2, "payroll_nonduplicated": False}
        response = client.post("/api/auto-repair-rate/R02/proposals", json=payload)
    assert response.status_code == 200
    calculation = response.json()["calculation"]
    assert calculation["candidate_yen_per_person_hour"] is None
    assert "payroll_nonduplicated_confirmation_required" in calculation["unknowns"]


def test_r02_endpoint_rejects_nan_numeric_values(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r02-nan.sqlite3"))
    with TestClient(app) as client:
        payload = {"proposal": fixture_proposal(), "gross_margin": 0.2, "payroll_nonduplicated": True}
        payload["proposal"]["allocable_cost_yen"] = float("nan")
        response = client.post(
            "/api/auto-repair-rate/R02/proposals", content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
