from copy import deepcopy
import unittest

from .contract import approved_common_scenario_fixture
from .e18 import ENGINE_ID, build_trace_tree, evaluate_tree, inspect_trace, run


class E18CalculationTraceTreeTests(unittest.TestCase):
    def test_tree_leaves_sum_to_common_approved_labor_and_link_evidence(self):
        scenario = approved_common_scenario_fixture()
        original = deepcopy(scenario)
        result = run(scenario)
        self.assertEqual(scenario, original)
        self.assertEqual(result["engine_id"], ENGINE_ID)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": 2.53, "typical": 2.78, "high": 3.03})
        tree = result["trace"][0]["tree"]
        self.assertEqual(evaluate_tree(tree), {
            "person_hours": result["labor"]["person_hours"],
            "elapsed_hours": result["labor"]["elapsed_hours"],
        })
        self.assertTrue(inspect_trace(tree, scenario)["valid"])
        self.assertTrue(all(leaf["input_refs"] for leaf in tree["children"]))
        self.assertTrue(all(leaf["input_hash"] == tree["input_hash"] for leaf in tree["children"]))
        base = next(leaf for leaf in tree["children"] if leaf["operation_id"] == "base_service")
        self.assertIn("/operations/0/hours", [item["path"] for item in base["input_refs"]])
        self.assertIn("/operations/1/hours", [item["path"] for item in base["input_refs"]])

    def test_changing_a_leaf_changes_tree_sum_and_audit_detects_tampering(self):
        scenario = approved_common_scenario_fixture()
        tree = build_trace_tree(scenario)
        wash = next(leaf for leaf in tree["children"] if leaf["operation_id"] == "wash")
        wash["result"]["person_hours"] = {"low": 1.1, "typical": 1.1, "high": 1.1}
        evaluated = evaluate_tree(tree)
        self.assertEqual(evaluated["person_hours"]["typical"], 3.13)
        audit = inspect_trace(tree, scenario)
        self.assertFalse(audit["valid"])
        self.assertIn("trace:stored_total_differs_from_leaf_sum", audit["issues"])
        self.assertIn("trace:leaf_sum_differs_from_labor_audit", audit["issues"])

    def test_wait_contributes_only_to_elapsed_and_unknown_wait_is_partial(self):
        scenario = approved_common_scenario_fixture()
        result = run(scenario)
        tree = result["trace"][0]["tree"]
        wait = next(leaf for leaf in tree["children"] if leaf["operation_id"] == "snow_melt")
        self.assertEqual(wait["result"]["person_hours"], {"low": 0.0, "typical": 0.0, "high": 0.0})
        self.assertEqual(wait["result"]["elapsed_hours"]["typical"], 0.5)

        unknown = deepcopy(scenario)
        next(op for op in unknown["operations"] if op["operation_id"] == "parts_wait")["elapsed_hours"] = None
        partial = run(unknown)
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["labor"]["person_hours"]["typical"], 2.13)
        self.assertEqual(partial["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})
        self.assertIn("parts_wait:elapsed_duration_unknown", partial["labor"]["unknowns"])

    def test_missing_subframe_evidence_stops_and_unknown_rule_pack_is_not_applied(self):
        scenario = approved_common_scenario_fixture()
        del scenario["fields"]["subframe_relevance"]
        result = run(scenario)
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertIn("subframe_relevance:required_not_zero", result["labor"]["unknowns"])

        gated = run(approved_common_scenario_fixture(), {"rule_version": "untrusted"})
        self.assertEqual(gated["status"], "missing-required")
        self.assertIn("rule_pack:dynamic_pack_unsupported_by_e18", gated["labor"]["unknowns"])

    def test_input_snapshot_mutation_breaks_reference_audit(self):
        scenario = approved_common_scenario_fixture()
        tree = build_trace_tree(scenario)
        changed = deepcopy(scenario)
        changed["operations"][0]["hours"] = 1.8
        audit = inspect_trace(tree, changed)
        self.assertFalse(audit["valid"])
        self.assertIn("trace:input_snapshot_hash_mismatch", audit["issues"])
        self.assertIn("trace:input_ref_value_mismatch", audit["issues"])


if __name__ == "__main__":
    unittest.main()
