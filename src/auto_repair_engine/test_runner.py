import copy
import unittest

from auto_repair_engine.contract import approved_common_scenario_fixture
from auto_repair_engine.runner import compare_engines, run_engine


class RunnerTests(unittest.TestCase):
    def test_adapter_enforces_common_envelope_and_preserves_scenario_snapshot(self):
        scenario = approved_common_scenario_fixture()
        original = copy.deepcopy(scenario)
        result = run_engine("e01", scenario)
        self.assertEqual(scenario, original)
        self.assertEqual(result["scenario_id"], scenario["scenario_id"])
        self.assertTrue({"engine_id", "rule_version", "status", "labor", "trace", "operation_keys", "approvals"}.issubset(result))

    def test_compare_runs_same_scenario_copy_and_keeps_evidence_per_method(self):
        scenario = approved_common_scenario_fixture()
        original = copy.deepcopy(scenario)
        result = compare_engines(scenario, engine_ids=("e01",))
        self.assertEqual(scenario, original)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["engine_id"], "e01")
        self.assertEqual(result[0]["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})

    def test_unknown_engine_is_rejected(self):
        with self.assertRaises(ValueError):
            run_engine("e99", {})


if __name__ == "__main__":
    unittest.main()
