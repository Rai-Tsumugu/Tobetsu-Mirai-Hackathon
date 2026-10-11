"""R11-R14 focused formulas, missing-data gates, and approval flows."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.r11_seasonal_scenarios import calculate_seasonal_scenarios
from backend.r12_cost_events import calculate_as_of
from backend.r13_cost_wizard import calculate_wizard
from backend.r14_csv_import import parse_cost_csv

FIXTURES = Path(__file__).parents[2] / "fixtures"
LEGACY_FIXTURES = Path(__file__).parents[3] / "fixtures"


def data(name):
    path = FIXTURES / name
    if not path.exists():
        path = LEGACY_FIXTURES / name
    value = json.loads(path.read_text(encoding="utf-8"))
    value.pop("fictional_fixture", None)
    return value


def approve(client, version):
    response = client.post(f"/api/auto-repair-rate/proposals/{version['proposal_id']}/approval", json={
        "approved_yen_per_person_hour": version["calculation"]["candidate_yen_per_person_hour"],
        "effective_from": "2026-11-01", "approved_by": "確認者", "approval_reason": "根拠確認済み"})
    assert response.status_code == 200, response.text
    assert response.json()["labor_rate"] is not None


def test_r11_three_independent_rates_and_unknown_stops_only_its_scenario():
    cases = [{"name":"annual","fixed_cost_yen":100,"variable_cost_yen":20,"H_period_bill":10,"basis":"annual"},
             {"name":"winter","fixed_cost_yen":100,"variable_cost_yen":50,"H_period_bill":5,"basis":"winter"},
             {"name":"smoothed","fixed_cost_yen":100,"variable_cost_yen":10,"H_period_bill":None,"basis":"12 months"}]
    result = calculate_seasonal_scenarios(cases)
    assert [case["rate_yen_per_person_hour"] for case in result["scenarios"]] == [12, 30, None]
    assert result["requires_human_scenario_choice"] is True


def test_r11_api_requires_explicit_choice_and_approval_creates_labor_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r11.sqlite3"))
    with TestClient(app) as client:
        payload = data("r11_seasonal_scenarios.json")
        payload["selected_scenario"] = None
        assert client.post("/api/auto-repair-rate/R11/proposals", json=payload).json()["status"] == "blocked"
        payload["selected_scenario"] = "annual"
        proposal = client.post("/api/auto-repair-rate/R11/proposals", json=payload).json()
        assert proposal["status"] == "draft" and proposal["labor_rate"] is None
        assert proposal["calculation"]["candidate_yen_per_person_hour"] == pytest.approx(6000)
        assert proposal["calculation"]["excluded_items"][0]["included_in_labor_pool"] is False
        saved_basis = {row["label"]: row["value"] for row in proposal["calculation"]["basis"]}
        assert saved_basis["annual シナリオ"] == "2026年度 / 架空の通年基準"
        assert saved_basis["選択シナリオの対象期間"] == "2026年度"
        assert saved_basis["選択シナリオの前提"] == "架空の通年基準"
        approve(client, proposal)


@pytest.mark.parametrize("hours", [None, 0])
def test_r11_scenario_unknown_or_zero_hours_blocks_that_rate(hours):
    result = calculate_seasonal_scenarios([{"name":"winter","fixed_cost_yen":10,"variable_cost_yen":1,"H_period_bill":hours}])
    assert result["scenarios"][0]["rate_yen_per_person_hour"] is None


def test_r12_as_of_applies_only_effective_events_and_requires_hours():
    events = [{"event_id":"e1","category":"heating","old_amount_yen":10,"new_amount_yen":12,"effective_from":"2026-11-01"},
              {"event_id":"e2","category":"heating","old_amount_yen":12,"new_amount_yen":15,"effective_from":"2026-12-01"}]
    from datetime import date
    result = calculate_as_of({"heating": 10, "rent": 20}, events, date(2026, 11, 15), 2)
    assert result["costs_as_of_yen"]["heating"] == 12
    assert result["candidate_yen_per_person_hour"] == 16
    with_materials = calculate_as_of({"rent": 20, "materials": 100}, [], date(2026, 11, 15), 2)
    assert with_materials["total_cost_yen"] == 20
    assert with_materials["candidate_yen_per_person_hour"] == 10
    assert with_materials["excluded_materials_as_of_yen"] == {"materials": 100}
    assert calculate_as_of({"rent": 10}, [], date(2026, 11, 1), None)["candidate_yen_per_person_hour"] is None


def test_r12_requires_reconciled_initial_baseline_and_reports_period_semantics():
    from datetime import date
    event = {"event_id":"e1", "category":"heating", "old_amount_yen":10,
             "new_amount_yen":12, "effective_from":"2026-11-01"}
    ok = calculate_as_of({"heating":10}, [event], date(2026,11,15), 2)
    assert ok["candidate_yen_per_person_hour"] == 6
    assert "2026-11-15" in ok["period_semantics"]
    mismatch = calculate_as_of({"heating":9}, [event], date(2026,11,15), 2)
    assert mismatch["candidate_yen_per_person_hour"] is None
    assert mismatch["applied_event_ids"] == []
    missing = calculate_as_of({"heating":None}, [event], date(2026,11,15), 2)
    assert missing["candidate_yen_per_person_hour"] is None


def test_r12_event_history_is_append_only_and_approval_saves_new_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r12.sqlite3"))
    with TestClient(app) as client:
        payload = data("r12_cost_events.json")
        event = client.post("/api/auto-repair-rate/R12/cost-events", json=payload["event"])
        assert event.status_code == 200, event.text
        stale = client.post("/api/auto-repair-rate/R12/cost-events", json={**payload["event"], "new_amount_yen": 800000})
        assert stale.status_code == 409
        preview = client.post("/api/auto-repair-rate/R12/rates/preview", json=payload["preview"]).json()
        assert preview["candidate_yen_per_person_hour"] == pytest.approx(5933.3333333)
        stopped = client.post("/api/auto-repair-rate/R12/rates/preview", json={**payload["preview"], "H_period_bill": 0}).json()
        assert stopped["candidate_yen_per_person_hour"] is None
        proposal = client.post("/api/auto-repair-rate/R12/proposals", json=payload["preview"]).json()
        approve(client, proposal)
        history = client.get("/api/auto-repair-rate/R12/cost-events").json()
        assert len(history) == 1 and history[0]["event_id"] == event.json()["event_id"]
        assert proposal["calculation"]["excluded_items"][0]["included_in_labor_pool"] is False


def test_r13_monthly_cost_is_annualized_and_server_uses_r01():
    cards = [{"category":"rent","label":"rent","amount":100,"period":"monthly","include_flag":True,"status":"estimated","source":"demo","notes":"fixture"},
             {"category":"heating","label":"heating","amount":20,"period":"annual","include_flag":True,"status":"estimated","source":"demo","notes":"fixture"},
             {"category":"equipment","label":"equipment","amount":30,"period":"annual","include_flag":True,"status":"estimated","source":"demo","notes":"fixture"},
             {"category":"payroll","label":"payroll","amount":50,"period":"annual","include_flag":True,"status":"estimated","source":"demo","notes":"fixture"},
             {"category":"materials","label":"materials","amount":200,"period":"annual","include_flag":False,"status":"estimated","source":"demo","notes":"excluded"}]
    for card in cards:
        card["source"], card["notes"] = "demo", "fixture"
    result = calculate_wizard(cards, 100, .5, "2026-01-01", "2026-12-31", "2026-11-01", True)
    assert result["annual_allocable_cost_yen"] == 1300
    assert float(result["candidate_yen_per_person_hour"]) == 26
    assert result["labor_rate_issued"] is False


def test_r13_payroll_overlap_requires_explicit_human_confirmation():
    cards = data("r13_cost_wizard.json")["cards"]
    blocked = calculate_wizard(cards, 100, .5, "2026-01-01", "2026-12-31", "2026-11-01")
    assert blocked["candidate_yen_per_person_hour"] is None
    assert any("給与" in b and "確認" in b for b in blocked["blockers"])
    confirmed = calculate_wizard(cards, 100, .5, "2026-01-01", "2026-12-31", "2026-11-01", True)
    payroll = next(row for row in confirmed["included_costs"] if row["category"] == "payroll")
    assert payroll["payroll_overlap"] is False and payroll["payroll_overlap_confirmed"] is True


def test_r13_unknown_is_not_zero_and_materials_cannot_be_included():
    payload = data("r13_cost_wizard.json")
    payload["cards"][3]["amount"] = None
    result = calculate_wizard(payload["cards"], payload["total_person_hours"], payload["u_period"], payload["period_start"], payload["period_end"], payload["effective_from"])
    assert result["candidate_yen_per_person_hour"] is None
    payload["cards"][4]["include_flag"] = True
    blocked = calculate_wizard(payload["cards"], payload["total_person_hours"], payload["u_period"], payload["period_start"], payload["period_end"], payload["effective_from"])
    assert any("材料費" in item for item in blocked["blockers"])


def test_r13_api_saves_candidate_but_approval_is_separate(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r13.sqlite3"))
    with TestClient(app) as client:
        payload = data("r13_cost_wizard.json")
        payload["confirm_payroll_overlap"] = True
        proposal = client.post("/api/auto-repair-rate/R13/proposals", json=payload)
        assert proposal.status_code == 200, proposal.text
        assert proposal.json()["status"] == "draft"
        assert proposal.json()["labor_rate"] is None
        approve(client, proposal.json())


def test_r14_csv_preview_allocates_only_explicit_approved_mappings_and_blocks_unknowns():
    payload = data("r14_cost_import.json")
    result = parse_cost_csv(payload["csv_contents"].replace("tax_exempt", "tax_excluded"), payload["mappings"], True, True,
                            date_from(payload["period_start"]), date_from(payload["period_end"]))
    assert result["allocated_totals_yen"] == {"rent": 1200000, "payroll": 5200000}
    assert result["raw_csv_persisted"] is False
    unknown = parse_cost_csv(payload["csv_contents"], [], True, True)
    assert unknown["allocated_totals_yen"] == {}
    assert any("未知" in item for item in unknown["blockers"])


def date_from(value):
    from datetime import date
    return date.fromisoformat(value)


def test_r14_duplicate_and_materials_require_explicit_confirmation():
    csv_text = "date,account,amount,tax_mode\n2026-01-31,材料,100,tax_excluded\n2026-01-31,材料,100,tax_excluded\n"
    mapping = [{"account":"材料","category":"materials","approved":True}]
    blocked = parse_cost_csv(csv_text, mapping, False, False)
    assert "重複行を除外する確認が必要です" in blocked["blockers"]
    assert "別請求材料の二重計上を除外する確認が必要です" in blocked["blockers"]
    confirmed = parse_cost_csv(csv_text, mapping, True, True)
    assert confirmed["allocated_totals_yen"] == {}
    assert sum(row["duplicate_excluded"] for row in confirmed["rows"]) == 1


def test_r14_tax_modes_must_be_uniform_within_allocated_labor_pool():
    csv_text = "date,account,amount,tax_mode\n2026-01-31,家賃,100,tax_exempt\n2026-01-31,給与,200,tax_excluded\n"
    mappings = [{"account":"家賃","category":"rent","approved":True},
                {"account":"給与","category":"payroll","approved":True}]
    mixed = parse_cost_csv(csv_text, mappings, True, True)
    assert mixed["allocated_totals_yen"] == {}
    assert any("税抜" in item for item in mixed["blockers"])
    uniform = parse_cost_csv(csv_text.replace("tax_exempt", "tax_excluded"), mappings, True, True)
    assert uniform["allocated_totals_yen"] == {"rent": 100, "payroll": 200}
    assert uniform["blockers"] == []
    exempt = parse_cost_csv(csv_text.replace("tax_excluded", "tax_exempt"), mappings, True, True)
    assert exempt["allocated_totals_yen"] == {}
    assert any("税抜" in b and "再取込" in b for b in exempt["blockers"])


def test_r14_api_blocks_unapproved_mappings(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r14_unapproved.sqlite3"))
    payload = data("r14_cost_import.json")
    payload["csv_contents"] = payload["csv_contents"].replace("tax_exempt", "tax_excluded")
    payload["mappings"] = [{**mapping, "approved": False} for mapping in payload["mappings"]]
    with TestClient(app) as client:
        response = client.post("/api/auto-repair-rate/R14/rates/preview", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["allocated_totals_yen"] == {}
    assert any("未承認" in item for item in result["blockers"])


def test_r14_api_stores_only_summary_and_requires_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r14.sqlite3"))
    with TestClient(app) as client:
        payload = data("r14_cost_import.json")
        payload["csv_contents"] = payload["csv_contents"].replace("tax_exempt", "tax_excluded")
        response = client.post("/api/auto-repair-rate/R14/proposals", json=payload)
        assert response.status_code == 200, response.text
        proposal = response.json()
        assert proposal["status"] == "draft" and proposal["labor_rate"] is None
        serialized = json.dumps(proposal, ensure_ascii=False)
        assert "2026-01-31,家賃" not in serialized
        approve(client, proposal)


def test_r14_period_mismatch_blocks_allocated_totals():
    payload = data("r14_cost_import.json")
    result = parse_cost_csv(payload["csv_contents"], payload["mappings"], True, True,
                            date_from("2026-02-01"), date_from("2026-12-31"))
    assert result["allocated_totals_yen"] == {}
    assert "CSV行に指定期間外の日付があります" in result["blockers"]
