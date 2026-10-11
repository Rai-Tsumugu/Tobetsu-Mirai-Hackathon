from copy import deepcopy
import unittest
from .contract import approved_common_scenario_fixture
from .e20 import run

class E20WhatIfTests(unittest.TestCase):
    def test_hypothesis_changes_sandbox_result_and_preserves_parent(self):
        scenario = approved_common_scenario_fixture(); before = deepcopy(scenario)
        result = run(scenario, {"hypothesis": {"actor": "fixture_user", "reason": "test only", "operations": [{"operation_id": "wash", "hours": 0.4}]}})
        self.assertEqual(scenario, before)
        self.assertEqual(result["hypothesis"]["status"], "sandbox-proposed")
        self.assertFalse(result["hypothesis"]["approved"])
        self.assertNotEqual(result["hypothesis"]["parent_hash"], result["hypothesis"]["hypothesis_hash"])
        self.assertEqual(result["labor"]["person_hours"]["typical"], 2.43)

    def test_unaudited_hypothesis_is_rejected(self):
        result = run(approved_common_scenario_fixture(), {"hypothesis": {"operations": [{"operation_id": "wash", "hours": 2}]}})
        self.assertEqual(result["hypothesis"]["status"], "rejected")

if __name__ == "__main__": unittest.main()
