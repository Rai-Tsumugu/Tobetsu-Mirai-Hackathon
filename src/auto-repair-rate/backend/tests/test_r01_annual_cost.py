import json
import os
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[2]))
from backend.r01_annual_cost import (
    AnnualCostInput, CostRow, calculate_annual_cost, job_billable_hours,
)
from backend.app import app
from fastapi.testclient import TestClient


FIXTURE = Path(__file__).parents[2] / "fixtures" / "r01_annual_cost.json"


class AnnualCostTests(unittest.TestCase):
    def setUp(self):
        self.demo = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_calculates_6000_without_materials(self):
        result = calculate_annual_cost(self.demo)
        self.assertEqual(result["candidate_yen_per_person_hour"], "6000")
        self.assertEqual(result["H_period_bill"], "1200.00")
        self.assertEqual(result["annual_allocable_cost_yen"], 7200000)
        self.assertEqual([row["id"] for row in result["excluded_costs"]], ["materials"])
        self.assertEqual(result["approval_status"], "pending_human_approval")
        self.assertFalse(result["labor_rate_issued"])

    def test_unknown_included_cost_blocks_instead_of_becoming_zero(self):
        self.demo["costs"][0]["amount_yen"] = None
        self.demo["costs"][0]["status"] = "unknown"
        result = calculate_annual_cost(self.demo)
        self.assertIsNone(result["candidate_yen_per_person_hour"])
        self.assertTrue(any("計上額が不明" in item for item in result["blockers"]))

    def test_missing_and_zero_denominators_block(self):
        for field, value in (("H_period_total", 0), ("H_period_total", None),
                             ("u_period", 0), ("u_period", None)):
            case = {**self.demo, field: value}
            self.assertEqual(calculate_annual_cost(case)["candidate_status"], "blocked")

    def test_parts_cannot_be_included_in_labor_rate(self):
        self.demo["costs"][-1]["included_in_rate"] = True
        result = calculate_annual_cost(self.demo)
        self.assertIsNone(result["candidate_yen_per_person_hour"])
        self.assertTrue(any("部品・材料費" in item for item in result["blockers"]))

    def test_aggregate_must_reconcile_with_cost_lines(self):
        self.demo["annual_allocable_cost_yen"] = 7300000
        result = calculate_annual_cost(self.demo)
        self.assertIsNone(result["candidate_yen_per_person_hour"])
        self.assertTrue(any("一致しません" in item for item in result["blockers"]))

    def test_payroll_overlap_blocks_double_counting(self):
        self.demo["costs"][0]["payroll_overlap"] = True
        result = calculate_annual_cost(self.demo)
        self.assertTrue(any("重複計上" in item for item in result["blockers"]))

    def test_job_ratio_applies_only_to_total_person_hours(self):
        self.assertEqual(job_billable_hours(10, "total_person_hours", 0.8), Decimal("8.0"))
        self.assertEqual(job_billable_hours(8, "billable_person_hours", 0.2), Decimal("8"))

    def test_period_utilization_remains_separate_from_job_ratio(self):
        result = calculate_annual_cost(self.demo)
        self.assertEqual(result["H_period_bill"], "1200.00")
        self.assertFalse(result["job_ratio_applied_to_period_denominator"])

    def test_missing_hours_basis_does_not_fall_back_or_block_annual_rate(self):
        self.demo["hours_basis"] = None
        self.demo["job_person_hours"] = {"low": 2.5, "typical": 2.5, "high": 2.5}
        result = calculate_annual_cost(self.demo)
        self.assertEqual(result["candidate_yen_per_person_hour"], "6000")
        self.assertIsNone(result["shared_calculation"]["hours_basis"])
        self.assertIn("hours_basis", result["shared_calculation"]["job_unknowns"])

    def test_omitted_hours_basis_keeps_job_output_unknown_but_calculates_period_rate(self):
        self.demo.pop("hours_basis")
        self.demo["job_person_hours"] = {"low": 2.5, "typical": 2.5, "high": 2.5}
        result = calculate_annual_cost(self.demo)
        self.assertEqual(result["candidate_yen_per_person_hour"], "6000")
        self.assertIsNone(result["shared_calculation"]["hours_basis"])
        self.assertIsNone(result["shared_calculation"]["job_billable_person_hours"])
        self.assertIn("hours_basis", result["shared_calculation"]["job_unknowns"])

    def test_fractional_yen_blocks(self):
        self.demo["costs"][0]["amount_yen"] = 5200000.5
        result = calculate_annual_cost(self.demo)
        self.assertIsNone(result["candidate_yen_per_person_hour"])
        self.assertTrue(any("整数の円" in item for item in result["blockers"]))

    def test_r01_specific_blockers_are_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"AUTO_REPAIR_RATE_DB": str(Path(temp_dir) / "r01.sqlite3")}):
                with TestClient(app) as client:
                    response = client.post("/api/auto-repair-rate/R01/proposals", json={
                        "proposal": {
                            "module_id": "R01", "period_start": "2025-01-01",
                            "period_end": "2025-12-31", "effective_from": "2026-01-01",
                            "allocable_cost_yen": 7200001, "period_total_person_hours": 1600,
                            "u_period": 0.75, "hours_basis": None, "job_billable_ratio": 0.8,
                            "costs": [{
                                "cost_id": "wages", "label": "人件費", "amount_yen": 7200000,
                                "period": "2025年度", "source": None, "evidence_status": "assumed",
                                "billing_class": "labor_pool", "included_in_labor_pool": True,
                            }],
                            "evidence": [], "source": "fictional_simulator",
                        },
                        "payroll_overlap_cost_ids": ["wages"], "payroll_overlap_unconfirmed_cost_ids": ["wages"], "cost_evidence_by_id": {},
                    })
                    self.assertEqual(response.status_code, 200, response.text)
                    version = response.json()
                    self.assertEqual(version["status"], "blocked")
                    self.assertIsNone(version["calculation"]["candidate_yen_per_person_hour"])
                    unknowns = " ".join(version["calculation"]["unknowns"])
                    self.assertIn("重複計上", unknowns)
                    self.assertIn("出典", unknowns)
                    self.assertIn("一致しません", unknowns)
                    stored = client.get(f"/api/auto-repair-rate/R01/proposals/{version['proposal_id']}")
                    self.assertEqual(stored.status_code, 200)
                    self.assertEqual(stored.json()["status"], "blocked")

    def test_r01_api_rejects_non_finite_numeric_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"AUTO_REPAIR_RATE_DB": str(Path(temp_dir) / "r01.sqlite3")}):
                with TestClient(app) as client:
                    body = {
                        "proposal": {
                            "module_id": "R01", "period_start": "2025-01-01",
                            "effective_from": "2026-01-01", "allocable_cost_yen": float("nan"),
                            "period_total_person_hours": 1600, "u_period": 0.75,
                            "hours_basis": None, "costs": [], "evidence": [],
                        }
                    }
                    response = client.post(
                        "/api/auto-repair-rate/R01/proposals",
                        content=json.dumps(body, allow_nan=True),
                        headers={"content-type": "application/json"},
                    )
                    self.assertEqual(response.status_code, 422, response.text)

    def test_shared_api_requires_approval_and_persists_rate_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "r01.sqlite3"
            with patch.dict(os.environ, {"AUTO_REPAIR_RATE_DB": str(db_path)}):
                with TestClient(app) as client:
                    response = client.post("/api/auto-repair-rate/R01/proposals", json={
                        "proposal": {
                            "module_id": "R01",
                            "period_start": "2025-01-01",
                            "effective_from": "2026-01-01",
                            "allocable_cost_yen": 7200000,
                            "period_total_person_hours": 1600,
                            "u_period": 0.75,
                            "hours_basis": "total_person_hours",
                            "job_person_hours": {"low": 10, "typical": 10, "high": 10},
                            "job_billable_ratio": 0.8,
                            "costs": [
                                {"cost_id": "wages", "label": "人件費", "amount_yen": 7200000, "period": "2025年度", "source": "架空", "evidence_status": "assumed", "billing_class": "labor_pool", "included_in_labor_pool": True},
                                {"cost_id": "materials", "label": "材料費", "amount_yen": 300000, "period": "2025年度", "source": "架空", "evidence_status": "assumed", "billing_class": "separately_billed_item", "included_in_labor_pool": False}
                            ],
                            "evidence": [{
                                "label": "年間費用・人時入力", "value": "架空値", "unit": "simulator",
                                "status": "assumed", "source": "R01 fixture", "evidence_ref": None,
                                "recorded_at": "2026-10-11T00:00:00Z", "notes": "実データではない"
                            }],
                            "source": "fictional_simulator",
                            "notes": "R01 integration test"
                        },
                        "payroll_overlap_cost_ids": [],
                        "cost_evidence_by_id": {
                            "wages": "給与明細の年間集計（架空）",
                            "materials": "別請求した材料費の記録（架空）",
                        },
                    })
                    self.assertEqual(response.status_code, 200, response.text)
                    version = response.json()
                    self.assertEqual(version["status"], "draft")
                    self.assertEqual(version["calculation"]["candidate_yen_per_person_hour"], 6000)
                    self.assertEqual(version["calculation"]["denominator_person_hours"], 1200)
                    self.assertEqual(version["calculation"]["job_billable_person_hours"]["typical"], 8)
                    self.assertEqual(version["calculation"]["excluded_items"][0]["cost_id"], "materials")
                    self.assertIsNone(version["labor_rate"])
                    proposal_id = version["proposal_id"]
                    approval = client.post(
                        f"/api/auto-repair-rate/R01/proposals/{proposal_id}/approval",
                        json={"approved_yen_per_person_hour": 6000, "effective_from": "2026-01-01", "approved_by": "架空の承認者", "approval_reason": "試験用"},
                    )
                    self.assertEqual(approval.status_code, 200, approval.text)
                    self.assertEqual(approval.json()["status"], "approved")
                    self.assertEqual(approval.json()["labor_rate"]["yen_per_person_hour"], 6000)
                    self.assertEqual(approval.json()["labor_rate"]["effective_from"], "2026-01-01")
                    self.assertEqual(len(client.get("/api/labor-rates").json()), 1)
                    self.assertEqual(client.get(f"/api/auto-repair-rate/R01/proposals/{proposal_id}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
