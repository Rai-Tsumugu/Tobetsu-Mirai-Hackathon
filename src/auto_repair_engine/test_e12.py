"""Behavioral tests for dependency-based E12 delta recalculation."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from .contract import approved_common_scenario_fixture, common_scenario_fixture
from . import e07, e12


def trace_entry(result, stage):
    return next(item for item in result["trace"] if item.get("stage") == stage)


class E12DeltaRecalculationTests(unittest.TestCase):
    def test_index_maps_known_fields_and_unknown_fields_safely(self):
        scenario = approved_common_scenario_fixture()
        scenario["fields"]["new_observation"] = {"value": "x", "status": "unknown"}
        index = e12.build_dependency_index(scenario)
        self.assertEqual(index["rotor_seizure_hours"], ["rotor_seizure"])
        self.assertIn("wash", index["new_observation"])

    def test_changed_rotor_observation_rebuilds_only_dependent_row_and_matches_full(self):
        original = approved_common_scenario_fixture()
        original["fields"]["rotor_relevance"] = dict(original["fields"]["rotor_relevance"], value="unrelated")
        original["fields"].pop("rotor_seizure_hours")
        original["metadata"].pop("approved_condition_widths")
        baseline = e12.run(original)
        changed = deepcopy(original)
        changed["fields"]["rotor_relevance"] = dict(changed["fields"]["rotor_relevance"], value="relevant")
        changed["fields"]["rotor_seizure_hours"] = deepcopy(approved_common_scenario_fixture()["fields"]["rotor_seizure_hours"])
        changed["metadata"]["approved_condition_widths"] = deepcopy(approved_common_scenario_fixture()["metadata"]["approved_condition_widths"])
        result = e12.recalculate_delta(baseline["delta_snapshot"], changed)
        delta = trace_entry(result, "delta_recalculation")
        self.assertTrue(delta["cache_validated"])
        self.assertEqual(delta["dirty_operation_ids"], ["rotor_seizure"])
        self.assertIn("base_service", delta["reused_operation_ids"])
        self.assertEqual(result["labor"], e07.run(changed)["labor"])
        self.assertGreater(result["labor"]["person_hours"]["high"], baseline["labor"]["person_hours"]["high"])

    def test_unknown_or_approval_change_invalidates_related_row(self):
        scenario = approved_common_scenario_fixture()
        baseline = e12.run(scenario)
        edited = deepcopy(scenario)
        edited["fields"]["rotor_seizure_hours"]["status"] = "unknown"
        edited["metadata"]["approved_condition_widths"].pop("rotor_seizure_hours")
        result = e12.recalculate_delta(baseline["delta_snapshot"], edited)
        delta = trace_entry(result, "delta_recalculation")
        self.assertTrue(delta["cache_validated"])
        self.assertEqual(delta["dirty_operation_ids"], ["rotor_seizure"])
        self.assertIsNone(result["labor"]["person_hours"]["typical"])
        self.assertIn("rotor_seizure_hours:human_approval_required", result["labor"]["unknowns"])

    def test_approval_audit_metadata_change_invalidates_rotor(self):
        scenario = approved_common_scenario_fixture()
        baseline = e12.run(scenario)
        edited = deepcopy(scenario)
        edited["metadata"]["approved_condition_widths"]["rotor_seizure_hours"]["reason"] = "fictional revised approval"
        result = e12.recalculate_delta(baseline["delta_snapshot"], edited)
        delta = trace_entry(result, "delta_recalculation")
        self.assertTrue(delta["cache_validated"])
        self.assertEqual(delta["dirty_operation_ids"], ["rotor_seizure"])
        self.assertEqual(result["labor"]["person_hours"]["typical"], 2.13)

    def test_forged_snapshot_and_rule_version_change_force_full_recompute(self):
        scenario = approved_common_scenario_fixture()
        baseline = e12.run(scenario)
        forged = deepcopy(baseline["delta_snapshot"])
        forged["operation_rows"]["base_service"]["hours"]["typical"] = 999
        result = e12.recalculate_delta(forged, scenario)
        self.assertFalse(trace_entry(result, "delta_recalculation")["cache_validated"])
        self.assertEqual(result["labor"], e07.run(scenario)["labor"])
        changed_version = deepcopy(scenario)
        changed_version["rule_version"] = "fictional-rule-v2"
        version_result = e12.recalculate_delta(baseline["delta_snapshot"], changed_version)
        self.assertFalse(trace_entry(version_result, "delta_recalculation")["cache_validated"])

    def test_initial_missing_snapshot_is_safe_and_input_is_immutable(self):
        scenario = common_scenario_fixture()
        before = deepcopy(scenario)
        result = e12.run(scenario)
        self.assertEqual(scenario, before)
        delta = trace_entry(result, "delta_recalculation")
        self.assertFalse(delta["cache_validated"])
        self.assertEqual(result["labor"], e07.run(scenario)["labor"])

    def test_valid_cache_change_recalculates_one_row_without_full_e07(self):
        original = approved_common_scenario_fixture()
        baseline = e12.run(original)
        edited = deepcopy(original)
        edited["fields"]["rotor_seizure_hours"]["value"]["typical"] = 0.3
        edited["metadata"]["approved_condition_widths"]["rotor_seizure_hours"]["new_value"]["typical"] = 0.3
        with patch.object(e12.e07, "run", side_effect=AssertionError("unexpected full recompute")), \
                patch.object(e12, "_evaluate_operation", wraps=e12._evaluate_operation) as evaluate:
            delta = e12.recalculate_delta(baseline["delta_snapshot"], edited)
        self.assertTrue(trace_entry(delta, "delta_recalculation")["cache_validated"])
        self.assertEqual(trace_entry(delta, "delta_recalculation")["recomputed_operation_count"], 1)
        self.assertEqual([call.args[1] for call in evaluate.call_args_list], ["rotor_seizure"])
        self.assertEqual(delta["labor"]["person_hours"]["typical"], 2.18)

    def test_valid_cache_does_not_full_evaluate_current_input(self):
        scenario = approved_common_scenario_fixture()
        baseline = e12.run(scenario)
        edited = deepcopy(scenario)
        edited["fields"]["rotor_seizure_hours"]["value"]["typical"] = 0.3
        edited["metadata"]["approved_condition_widths"]["rotor_seizure_hours"]["new_value"]["typical"] = 0.3
        with patch.object(e12.e07, "run", side_effect=AssertionError("unexpected full pipeline")), \
                patch.object(e12, "_evaluate_operation", wraps=e12._evaluate_operation) as evaluate:
            delta = e12.recalculate_delta(baseline["delta_snapshot"], edited)
        self.assertTrue(trace_entry(delta, "delta_recalculation")["cache_validated"])
        self.assertEqual([call.args[1] for call in evaluate.call_args_list], ["rotor_seizure"])
        self.assertEqual(delta["labor"]["person_hours"]["typical"], 2.18)


if __name__ == "__main__":
    unittest.main()
