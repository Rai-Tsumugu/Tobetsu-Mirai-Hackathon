from copy import deepcopy
import unittest
from .contract import approved_common_scenario_fixture
from .e19 import run

class E19SidePanelTests(unittest.TestCase):
    def test_panels_group_observed_sides_without_filling_opposite(self):
        scenario = approved_common_scenario_fixture()
        scenario["operations"][0]["side"] = "left"
        before = deepcopy(scenario)
        result = run(scenario)
        self.assertEqual(scenario, before)
        self.assertEqual(len(result["side_panels"]["left"]), 1)
        self.assertEqual(result["side_panels"]["right"], [])
        self.assertEqual(result["side_comparison"][0]["difference"], {"status": "opposite_unobserved", "hours_delta": None})
        self.assertFalse(result["trace"][0]["unknown_opposite_autofilled"])

    def test_observed_pair_reports_actual_delta(self):
        scenario = approved_common_scenario_fixture()
        scenario["operations"][0].update({"side": "left", "hours": 1.0})
        right = dict(scenario["operations"][0], side="right", hours=1.4)
        scenario["operations"].append(right)
        result = run(scenario)
        self.assertEqual(result["side_comparison"][0]["difference"]["hours_delta"], 0.4)

if __name__ == "__main__": unittest.main()
