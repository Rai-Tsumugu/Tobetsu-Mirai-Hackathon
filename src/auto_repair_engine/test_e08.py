from copy import deepcopy
import unittest

from .contract import approved_common_scenario_fixture, reference_labor
from . import e08
from .e08 import Method, RULE_VERSION, run, register_method


class E08PluginRegistryTests(unittest.TestCase):
    def test_default_registry_uses_one_method_and_shared_reference_result(self):
        scenario = approved_common_scenario_fixture()
        original = deepcopy(scenario)
        result = run(scenario, {"method_id": "S05", "rule_version": "fixture-r7"})
        expected, _, _ = reference_labor(scenario)
        self.assertEqual(scenario, original)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["rule_version"], "fixture-r7")
        self.assertEqual(result["labor"], expected)
        self.assertEqual(result["trace"][1]["method_id"], "S05")

    def test_registered_method_evaluation_changes_actual_run_labor(self):
        baseline = run(approved_common_scenario_fixture())

        def evaluate(scenario):
            labor, _, _ = reference_labor(scenario)
            labor["person_hours"] = {"low": 9.0, "typical": 9.0, "high": 9.0}
            return labor

        register_method(Method("test_custom", ("operations",), lambda _: True, evaluate))
        result = run(approved_common_scenario_fixture(), {"method_id": "test_custom"})
        self.assertEqual(result["labor"]["person_hours"]["typical"], 9.0)
        self.assertNotEqual(result["labor"], baseline["labor"])
        self.assertEqual(result["trace"][-1]["method_id"], "test_custom")

    def test_duplicate_and_unknown_method_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            register_method(Method("S01", (), lambda _: True, lambda _: {}))
        result = run(approved_common_scenario_fixture(), {"method_id": "not_registered"})
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("method_id:unknown_or_unregistered", result["labor"]["unknowns"])
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

    def test_support_and_missing_required_observations_stop_with_null_ranges(self):
        scenario = approved_common_scenario_fixture()
        scenario.pop("basis_unit")
        result = run(scenario)
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("basis_unit:required", result["labor"]["unknowns"])
        self.assertIn("availability_stopped", [event["event"] for event in result["trace"]])
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

    def test_support_failure_has_explicit_reason(self):
        register_method(Method("test_unsupported", (), lambda _: "vehicle_scope:unsupported",
                               lambda _: reference_labor(approved_common_scenario_fixture())[0]))
        result = run(approved_common_scenario_fixture(), {"method_id": "test_unsupported"})
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("vehicle_scope:unsupported", result["labor"]["unknowns"])
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})

    def test_empty_or_non_contract_rule_version_is_not_accepted(self):
        result = run(approved_common_scenario_fixture(), {"method_id": "S01", "rule_version": " "})
        self.assertEqual(result["rule_version"], " ")
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("rule_version:required", result["labor"]["unknowns"])
        self.assertEqual(RULE_VERSION, "e08-plugin-registry-v1")


if __name__ == "__main__":
    unittest.main()
