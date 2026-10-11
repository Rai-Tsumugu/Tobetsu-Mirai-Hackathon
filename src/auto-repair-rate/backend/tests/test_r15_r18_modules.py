"""Focused R15-R18 formula, blocker, validation, and approval coverage."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend.r15_annual_summary import calculate_annual_summary
from backend.r16_capacity import calculate_capacity
from backend.r17_family_labor import calculate_family_labor
from backend.r18_incomplete_costs import calculate_incomplete_costs

FIXTURES = Path(__file__).parents[1] / "fixtures"
def fixture(name):
    row = json.loads((FIXTURES / name).read_text()); row.pop("fictional_fixture"); return row

def test_r15_annual_formula_and_zero_or_unknown_denominator_blocks():
    assert calculate_annual_summary(7200000,1600,.75,True)["candidate_yen_per_person_hour"] == pytest.approx(6000)
    assert calculate_annual_summary(7200000,0,.75,True)["candidate_yen_per_person_hour"] is None
    assert calculate_annual_summary(7200000,None,.75,True)["candidate_yen_per_person_hour"] is None
    assert calculate_annual_summary(7200000,1600,.75,False)["candidate_yen_per_person_hour"] is None

def test_r16_role_total_and_u_period_are_applied_once():
    r=calculate_capacity([{"weekly_hours":60,"work_weeks":48},{"weekly_hours":20,"work_weeks":48}],.7)
    assert r["period_total_person_hours"] == pytest.approx(3840)
    assert r["billable_person_hours"] == pytest.approx(2688)
    assert calculate_capacity([{"weekly_hours":20,"work_weeks":48}],0)["blockers"]

def test_r17_keeps_paid_and_imputed_family_candidates_separate():
    r=calculate_family_labor(4800000,400,1800,1200)
    assert r["paid_only_yen_per_person_hour"] == pytest.approx(4000)
    assert r["with_family_yen_per_person_hour"] == pytest.approx(4600)
    assert calculate_family_labor(4800000,400,None,1200)["with_family_yen_per_person_hour"] is None

def test_r18_does_not_zero_unknown_and_requires_uncertainty_acceptance():
    unknown=[{"label":"power","lower_yen":None,"upper_yen":None}]
    assert calculate_incomplete_costs(100,unknown,10,True)["lower_candidate"] is None
    bounded=[{"label":"power","lower_yen":20,"upper_yen":40}]
    assert calculate_incomplete_costs(100,bounded,10,False)["lower_candidate"] is None
    result=calculate_incomplete_costs(100,bounded,10,True,True)
    assert result["known_lower_bound"] == 10
    assert result["lower_candidate"] == 12 and result["upper_candidate"] == 14
    assert calculate_incomplete_costs(100,bounded,10,True,False)["lower_candidate"] is None

@pytest.mark.parametrize("name,expected", [("r15_annual_summary.json",6000),("r16_role_capacity.json",7200000/(3840*.7)),("r17_family_labor.json",4600),("r18_incomplete_costs.json",4900000/1200)])
def test_r15_r18_server_proposal_draft_then_common_approval(tmp_path,monkeypatch,name,expected):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB",str(tmp_path/(name+".sqlite")))
    module=name[:3].upper()
    with TestClient(app) as client:
        response=client.post(f"/api/auto-repair-rate/{module}/proposals",json=fixture(name))
        assert response.status_code==200,response.text
        version=response.json()
        assert version["status"]=="draft" and version["labor_rate"] is None
        assert version["calculation"]["candidate_yen_per_person_hour"]==pytest.approx(expected)
        approval=client.post(f"/api/auto-repair-rate/proposals/{version['proposal_id']}/approval",json={"approved_yen_per_person_hour":expected,"effective_from":"2027-01-01","approved_by":"社長","approval_reason":"架空 fixture の確認"})
        assert approval.status_code==200,approval.text
        assert approval.json()["labor_rate"]["yen_per_person_hour"]==pytest.approx(expected)

def test_module_inputs_reject_extra_and_nonfinite_values(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB",str(tmp_path/"validation.sqlite"))
    payload=fixture("r15_annual_summary.json");payload["client_rate"]=1
    with TestClient(app) as client:
        assert client.post("/api/auto-repair-rate/R15/proposals",json=payload).status_code==422
        payload=fixture("r15_annual_summary.json")
        raw=json.dumps(payload).replace("7200000", "Infinity")
        assert client.post("/api/auto-repair-rate/R15/proposals",content=raw,headers={"Content-Type":"application/json"}).status_code==422

def test_r18_blocks_candidate_until_materials_exclusion_is_confirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r18_materials.sqlite"))
    payload = fixture("r18_incomplete_costs.json")
    payload["materials_excluded"] = False
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R18/proposals", json=payload)
        assert response.status_code == 200
        version = response.json()
        assert version["status"] == "blocked"
        assert version["calculation"]["candidate_yen_per_person_hour"] is None
        assert any("材料" in message for message in version["calculation"]["unknowns"])
