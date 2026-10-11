import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from auto_repair_engine.api import create_app
except ImportError:
    TestClient = None
    create_app = None


@unittest.skipUnless(TestClient is not None, "install requirements.txt to run FastAPI integration checks")
class ApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(str(Path(self.temp_dir.name) / "api.sqlite3"))
        self.client = TestClient(self.app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_mobile_ui_and_fixture_are_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("整備工賃エンジン比較", response.text)
        self.assertEqual(self.client.get("/browser.mjs").status_code, 200)
        self.assertIn("function calculate", self.client.get("/browser.mjs").text)
        fixture = self.client.get("/api/fixture?approved_rotor=true")
        self.assertEqual(fixture.status_code, 200)
        self.assertTrue(fixture.json()["fictional_data"])
        pack = self.client.get("/api/engines/e02/example?approved_rotor=true")
        self.assertEqual(pack.status_code, 200)
        e02 = self.client.post("/api/engines/e02/calculate", json={"scenario_input":pack.json()["scenario_input"], "rule_pack":pack.json()["rule_pack"]})
        self.assertEqual(e02.status_code, 200)
        self.assertEqual(e02.json()["status"], "proposed")

    def test_estimate_requires_approved_scenario_and_persists_adjustment_audit(self):
        fixture = self.client.get("/api/fixture?approved_rotor=true").json()["scenario_input"]
        estimate = self.client.post("/api/estimates", json={
            "engine_id": "e01", "scenario_input": fixture,
            "final_labor_amount": 20000, "actor": "fictional_owner",
            "adjustment_reason": "fixture adjustment",
        })
        self.assertEqual(estimate.status_code, 201)
        body = estimate.json()
        self.assertEqual(body["labor_result"]["calculated_amount_range"], {"low": 16920, "typical": 19170, "high": 21420})
        self.assertEqual(body["approvals"][-1]["reason"], "fixture adjustment")
        history = self.client.get("/api/estimates").json()
        self.assertEqual(history[0]["estimate_id"], body["estimate_id"])
        detail = self.client.get(f"/api/estimates/{body['estimate_id']}").json()
        self.assertEqual(detail["approvals"][-1]["actor"], "fictional_owner")

    def test_estimate_idempotency_returns_same_saved_record_and_rejects_conflict(self):
        fixture = self.client.get("/api/fixture?approved_rotor=true").json()["scenario_input"]
        payload = {"engine_id":"e01", "scenario_input":fixture, "idempotency_key":"demo-save-1",
                   "final_labor_amount":20000, "actor":"fictional_owner", "adjustment_reason":"confirmed"}
        first = self.client.post("/api/estimates", json=payload)
        second = self.client.post("/api/estimates", json=payload)
        self.assertEqual(first.status_code, 201); self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["estimate_id"], second.json()["estimate_id"])
        changed = {**payload, "final_labor_amount":21000}
        self.assertEqual(self.client.post("/api/estimates", json=changed).status_code, 409)
        self.assertEqual(len(self.client.get("/api/estimates").json()), 1)

    def test_integrated_schema_calculate_save_and_reload(self):
        schema=self.client.get("/api/integrated/schema");self.assertEqual(schema.status_code,200)
        fixture=self.client.get("/api/fixture?approved_rotor=true").json()["scenario_input"]
        result=self.client.post("/api/engines/integrated/calculate",json={"scenario_input":fixture})
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()["status"],"proposed")
        payload={"engine_id":"integrated","scenario_input":fixture,"client_proposal":result.json(),
            "idempotency_key":"integrated-save","final_labor_amount":20000,"actor":"fictional_owner","adjustment_reason":"fixture confirmation"}
        saved=self.client.post("/api/estimates",json=payload);self.assertEqual(saved.status_code,201,saved.text)
        loaded=self.client.get(f"/api/estimates/{saved.json()['estimate_id']}")
        self.assertEqual(loaded.status_code,200);self.assertEqual(loaded.json()["engine_id"],"integrated")

    def test_compare_runs_all_thirty_engine_ids(self):
        fixture = self.client.get("/api/fixture?approved_rotor=true").json()["scenario_input"]
        response = self.client.post("/api/compare", json={"scenario_input":fixture})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["results"]), 30)
        self.assertTrue(all("labor" in item and "trace" in item for item in response.json()["results"]))

    def test_e28_rejects_tampered_client_proposal_before_save(self):
        fixture = self.client.get("/api/fixture?approved_rotor=true").json()["scenario_input"]
        response = self.client.post("/api/estimates", json={"engine_id":"e28", "scenario_input":fixture,
            "client_proposal":{"rule_version":fixture["rule_version"],"labor":{"person_hours":{"low":0,"typical":0,"high":0}}},
            "final_labor_amount":10000,"actor":"fictional_owner","adjustment_reason":"test"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get("/api/estimates").json(), [])

    def test_invalid_requests_are_rejected_without_estimate(self):
        self.assertEqual(self.client.post("/api/compare", json={}).status_code, 422)
        fixture = self.client.get("/api/fixture?approved_rotor=true").json()["scenario_input"]
        invalid = dict(fixture)
        invalid["labor_rate"] = {"value": float("inf"), "status": "confirmed"}
        self.assertEqual(self.client.post("/api/estimates", json={"engine_id": "e01", "scenario_input": invalid}).status_code, 422)
        self.assertEqual(self.client.post("/api/estimates", json={"engine_id": "e01", "scenario_input": fixture,
                                                                     "final_labor_amount": -1, "actor": "owner",
                                                                     "adjustment_reason": "invalid"}).status_code, 422)
        self.assertEqual(self.client.get("/api/estimates").json(), [])


if __name__ == "__main__":
    unittest.main()
