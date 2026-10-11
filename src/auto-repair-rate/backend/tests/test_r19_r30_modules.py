from datetime import date
from fastapi.testclient import TestClient
from backend.app import app


def base(**values):
    return {"period_start": "2026-01-01", "source_date": "2026-10-01", "effective_from": "2026-11-01",
            "source": "架空シミュレータ", "evidence_ref": "架空例", "evidence_notes": "架空入力", **values}


def test_all_r19_r30_routers_are_discovered():
    with TestClient(app) as client:
        ids = {row["module_id"] for row in client.get("/api/auto-repair-rate/modules").json()}
    assert {f"R{n}" for n in range(19, 31)} <= ids


def test_default_ui_payload_shapes_are_accepted_by_all_module_apis():
    payloads = {
        19: {"annual_cost_yen": 1200000, "annual_billable_hours": 600, "valid_from": "2026-10-01"},
        20: {"workers": [{"id": "tech-a", "annual_cost_yen": 3600000, "annual_billable_hours": 1800}], "job_hours_by_worker": {"tech-a": 2}},
        21: {"category_id": "general", "category_name": "一般整備", "allocation_share": 0, "direct_cost_yen": 100, "shared_cost_yen": 0, "billable_hours": 1},
        22: {"rate_type": "customer", "annual_cost_yen": None, "annual_billable_hours": None, "customer_rate_yen": None},
        23: {"last_review_date": "2026-10-01", "interval_months": 12, "next_review_date": "2027-10-01", "current_rate_yen": None, "allocable_cost_yen": None, "billable_hours": None},
        24: {"metric": "cost", "old_value": None, "new_value": None, "threshold_ratio": .1, "allocable_cost_yen": None, "billable_hours": 1},
        25: {"source_proposal_id": None, "current_rate_yen": None, "approval_reason": "確認待ち", "approver_role": "owner_review_required"},
        26: {"actual_labor_revenue_yen": None, "target_revenue_yen": None, "billed_hours": None, "allocable_cost_yen": None},
        27: {"billable_hours": None, "profit_yen": 0, "cost_items": [{"label": "家賃", "amount_yen": 120000, "included_in_labor_pool": True, "billing_class": "labor_pool"}]},
        28: {"annual_cost_yen": None, "annual_billable_hours": None, "winter_heating_yen": None, "winter_billable_hours": None},
        29: {"current_rate_yen": None, "candidate_rate_yen": None, "job_billable_hours": {"low": 1, "typical": 2, "high": 3}},
        30: {"required_denominator": None, "allocable_cost_yen": None, "evidence_items": []},
    }
    with TestClient(app) as client:
        for number, values in payloads.items():
            response = client.post(f"/api/auto-repair-rate/R{number}/rates/preview", json=base(**values))
            assert response.status_code == 200, f"R{number}: {response.text}"


def test_r19_calculates_server_side_and_blocks_zero_denominator():
    with TestClient(app) as client:
        good = client.post("/api/auto-repair-rate/R19/rates/preview", json=base(
            annual_cost_yen=1_200_000, annual_billable_hours=600, valid_from="2026-11-01")).json()
        zero = client.post("/api/auto-repair-rate/R19/rates/preview", json=base(
            annual_cost_yen=1_200_000, annual_billable_hours=0, valid_from="2026-11-01")).json()
    assert good["candidate_yen_per_person_hour"] == 2000
    assert zero["status"] == "blocked" and zero["candidate_yen_per_person_hour"] is None


def test_r20_internal_worker_cost_is_not_customer_labor_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r20.sqlite3"))
    with TestClient(app) as client:
        proposal = client.post("/api/auto-repair-rate/R20/proposals", json=base(
            workers=[{"id": "worker-a", "annual_cost_yen": 3_600_000, "annual_billable_hours": 1800}],
            job_hours_by_worker={"worker-a": 2})).json()
        approval = client.post(f"/api/auto-repair-rate/proposals/{proposal['proposal_id']}/approval", json={
            "approved_yen_per_person_hour": 2000, "effective_from": "2026-11-01", "approved_by": "owner", "approval_reason": "review"})
    assert proposal["rate_type"] == "internal" and proposal["rate_scope"].startswith("worker:")
    assert approval.status_code == 409


def test_r21_category_isolated_and_r28_winter_waits_for_hours(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "scopes.sqlite3"))
    with TestClient(app) as client:
        cat = client.post("/api/auto-repair-rate/R21/proposals", json=base(
            category_id="paint", category_name="塗装", direct_cost_yen=1000, shared_cost_yen=500,
            allocation_share=.5, billable_hours=2)).json()
        winter = client.post("/api/auto-repair-rate/R28/rates/preview", json=base(
            annual_cost_yen=1000, annual_billable_hours=1, winter_heating_yen=200, selected_scenario="winter")).json()
        annual = client.post("/api/auto-repair-rate/R28/rates/preview", json=base(
            annual_cost_yen=1000, annual_billable_hours=1, winter_heating_yen=200, selected_scenario="annual")).json()
    assert cat["rate_scope"] == "category:paint"
    assert winter["status"] == "blocked" and winter["candidate_yen_per_person_hour"] is None
    assert annual["status"] == "draft" and annual["candidate_yen_per_person_hour"] == 1000


def test_r30_missing_evidence_blocks_even_when_candidate_is_supplied():
    with TestClient(app) as client:
        result = client.post("/api/auto-repair-rate/R30/rates/preview", json=base(
            required_denominator=100, allocable_cost_yen=250000, evidence_items=[])).json()
    assert result["status"] == "blocked" and result["candidate_yen_per_person_hour"] is None
    assert any("cost" in item for item in result["blockers"])


def test_r30_requires_material_exclusion_and_values_matching_confirmed_evidence():
    evidence = [
        {"key": "cost", "label": "配賦費用", "status": "confirmed", "source": "月次報告", "confirmed_at": "2026-10-01", "value": 250000, "unit": "円"},
        {"key": "billable_hours", "label": "請求可能人時", "status": "confirmed", "source": "作業実績", "confirmed_at": "2026-10-01", "value": 100, "unit": "人時"},
    ]
    with TestClient(app) as client:
        payload = base(required_denominator=100, allocable_cost_yen=250000, evidence_items=evidence)
        unconfirmed_materials = client.post("/api/auto-repair-rate/R30/rates/preview", json=payload).json()
        payload["materials_excluded"] = True
        confirmed = client.post("/api/auto-repair-rate/R30/rates/preview", json=payload).json()
        payload["allocable_cost_yen"] = 300000
        mismatched = client.post("/api/auto-repair-rate/R30/rates/preview", json=payload).json()
    assert unconfirmed_materials["status"] == "blocked"
    assert confirmed["candidate_yen_per_person_hour"] == 2500
    assert mismatched["status"] == "blocked"


def test_r25_reviews_existing_proposal_without_changing_candidate_or_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r25.sqlite3"))
    with TestClient(app) as client:
        source = client.post("/api/auto-repair-rate/R19/proposals", json=base(
            annual_cost_yen=1200000, annual_billable_hours=600, valid_from="2026-11-01")).json()
        reviewed = client.post("/api/auto-repair-rate/R25/proposals", json=base(
            source_proposal_id=source["proposal_id"], current_rate_yen=1500,
            approval_reason="保存済み計算の確認", approver_role="owner_review_required")).json()
        rejected = client.post("/api/auto-repair-rate/R25/rates/preview", json=base(
            candidate_yen=999999, current_rate_yen=1500, approval_reason="任意単価",
            approver_role="owner_review_required"))
    assert reviewed["proposal_id"] == source["proposal_id"]
    assert reviewed["calculation"]["candidate_yen_per_person_hour"] == 2000
    assert reviewed["rate_scope"] == source["rate_scope"]
    assert rejected.status_code == 422


def test_r23_schedule_rejects_inconsistent_date_and_retains_valid_schedule(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r23-schedule.sqlite3"))
    valid = {"last_review_date": "2026-01-31", "interval_months": 1, "next_review_date": "2026-02-28",
             "capacity_person_hours": 100, "source": "実績", "evidence_ref": "schedule-1"}
    with TestClient(app) as client:
        rejected = client.post("/api/auto-repair-rate/R23/schedule", json={**valid, "next_review_date": "2026-03-01"})
        saved = client.post("/api/auto-repair-rate/R23/schedule", json=valid)
        loaded = client.get("/api/auto-repair-rate/R23/schedule")
    assert rejected.status_code == 422
    assert saved.status_code == 200
    assert loaded.status_code == 200 and loaded.json()["schedule"]["next_review_date"] == "2026-02-28"
