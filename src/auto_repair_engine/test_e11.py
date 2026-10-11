from copy import deepcopy
import unittest

from .contract import approved_common_scenario_fixture
from . import e11


class E11IndependentComparisonTests(unittest.TestCase):
    def test_methods_are_independent_and_unavailable_are_separate(self):
        scenario = approved_common_scenario_fixture()
        before = deepcopy(scenario)
        comparison = e11.compare_methods(scenario)
        self.assertEqual(scenario, before)
        self.assertEqual([r["method"] for r in comparison["runs"]], ["A", "B"])
        self.assertEqual(comparison["unavailable"]["C"], "method_C:not_implemented")
        chosen = e11.select_method(comparison, "A", "reviewer", "根拠の適用範囲を確認した")
        self.assertEqual(chosen["labor"]["person_hours"], comparison["runs"][0]["labor"]["person_hours"])
        self.assertEqual(len(chosen["selection"]["original_alternatives"]), 2)

    def test_selected_method_changes_actual_labor_and_requires_audit(self):
        scenario = approved_common_scenario_fixture()
        comparison = e11.compare_methods(scenario, ["A", "B"])
        comparison["runs"][1]["labor"]["person_hours"] = {"low": 8, "typical": 8, "high": 8}
        result = e11.select_method(comparison, "B", "human", "independently chose this run")
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertIn("comparison:payload_tampered", result["labor"]["unknowns"])
        self.assertIsNone(e11.select_method(comparison, "B", "", "why")["selection"])

    def test_input_version_and_alternatives_are_bound_to_recalculation(self):
        scenario = approved_common_scenario_fixture()
        comparison = e11.compare_methods(scenario)
        comparison["runs"][1]["labor"]["breakdown"].clear()
        result = e11.select_method(comparison, "B", "human", "verified")
        self.assertIsNone(result["selection"])
        self.assertIn("comparison:payload_tampered", result["labor"]["unknowns"])
        fresh = e11.compare_methods(scenario)
        result = e11.select_method(fresh, "A", "human", "verified", {**scenario, "person_count": 999})
        self.assertIn("comparison:input_binding_invalid", result["labor"]["unknowns"])
        result = e11.select_method(fresh, "A", "human", "verified", scenario, "wrong-version")
        self.assertIn("comparison:rule_version_binding_invalid", result["labor"]["unknowns"])

    def test_missing_unavailable_or_evidence_incomplete_never_falls_back(self):
        comparison = e11.compare_methods(approved_common_scenario_fixture())
        absent = e11.select_method(comparison, "missing", "human", "reason")
        self.assertEqual(absent["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertIn("selected_method:unavailable_or_missing", absent["labor"]["unknowns"])
        incomplete = deepcopy(comparison)
        incomplete["runs"][0]["unknowns"] = ["evidence:missing"]
        incomplete["comparison_hash"] = e11._hash({key: value for key, value in incomplete.items() if key != "comparison_hash"})
        result = e11.select_method(incomplete, "A", "human", "reason")
        self.assertIn("selected_method:evidence_incomplete", result["labor"]["unknowns"])

    def test_run_requires_explicit_choice_and_preserves_method_trace(self):
        scenario = approved_common_scenario_fixture()
        before = deepcopy(scenario)
        result = e11.run(scenario)
        self.assertEqual(scenario, before)
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("selected_method:human_choice_required", result["labor"]["unknowns"])
        chosen = e11.run(scenario, {"selected_method": "B", "actor": "human", "reason": "review"})
        self.assertEqual(chosen["selection"]["method"], "B")
        self.assertEqual(chosen["labor"], chosen["method_runs"][1]["labor"])
        self.assertEqual(chosen["trace"][0]["method_runs"], chosen["method_runs"])


if __name__ == "__main__":
    unittest.main()
