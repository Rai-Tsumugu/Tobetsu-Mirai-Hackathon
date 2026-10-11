from copy import deepcopy
import unittest

from .contract import approved_common_scenario_fixture
from .e07 import ENGINE_ID, run, validate_stage


class E07ValidationPipelineTests(unittest.TestCase):
    def test_common_fixture_runs_all_stages_with_concrete_outputs_and_hashes(self):
        scenario = approved_common_scenario_fixture()
        original = deepcopy(scenario)
        result = run(scenario)
        self.assertEqual(scenario, original)
        self.assertEqual(result["engine_id"], ENGINE_ID)
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": 2.53, "typical": 2.78, "high": 3.03})
        self.assertEqual([event["stage"] for event in result["trace"]],
                         ["validate", "normalize", "expand", "sum", "audit"])
        self.assertTrue(all(len(event["input_hash"]) == 64 for event in result["trace"]))
        self.assertTrue(all(event["rows"] for event in result["trace"]))
        carry = next(row for row in result["trace"][2]["rows"]
                     if row["operation_id"] == "replacement_carry")
        self.assertEqual(carry["person_hours"], 0.2)

    def test_normalization_alias_and_expansion_change_calculated_result(self):
        scenario = approved_common_scenario_fixture()
        snow = next(row for row in scenario["operations"] if row["operation_id"] == "snow_melt")
        snow.pop("elapsed_hours")
        snow["duration_hours"] = 1.2
        carry = next(row for row in scenario["operations"] if row["operation_id"] == "replacement_carry")
        carry["person_count"] = 3
        result = run(scenario)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["labor"]["person_hours"]["typical"], 2.23)
        self.assertEqual(result["labor"]["elapsed_hours"]["typical"], 3.48)
        normalized_snow = next(row for row in result["trace"][1]["rows"]
                               if row["operation_id"] == "snow_melt")
        self.assertEqual(normalized_snow["normalized"]["elapsed_hours"], 1.2)
        self.assertIn("duration_hours", normalized_snow["aliases_resolved"])
        expanded_carry = next(row for row in result["trace"][2]["rows"]
                              if row["operation_id"] == "replacement_carry")
        self.assertEqual(expanded_carry["person_hours"], 0.3)

    def test_points_duplicate_operations_and_invalid_numbers_stop_pipeline(self):
        points = approved_common_scenario_fixture()
        points["basis_unit"] = "points"
        result = run(points)
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertEqual([event["stage"] for event in result["trace"]], ["validate"])
        self.assertIn("basis_unit:person_hour_required", result["labor"]["unknowns"])

        duplicate = approved_common_scenario_fixture()
        duplicate["operations"].append(deepcopy(duplicate["operations"][0]))
        self.assertIn("base_service:duplicate_operation_id", validate_stage(duplicate).issues)

        bad_time = approved_common_scenario_fixture()
        next(row for row in bad_time["operations"] if row["operation_id"] == "wash")["hours"] = float("inf")
        self.assertIn("wash:hours_must_be_finite_nonnegative", validate_stage(bad_time).issues)

    def test_unit_mismatch_nonfinite_person_count_and_unknown_operation_rejected(self):
        scenario = approved_common_scenario_fixture()
        next(row for row in scenario["operations"] if row["operation_id"] == "base_service")["unit"] = "points"
        next(row for row in scenario["operations"] if row["operation_id"] == "replacement_carry")["person_count"] = float("nan")
        scenario["operations"].append({"operation_id": "surprise", "hours": 1})
        issues = validate_stage(scenario).issues
        self.assertIn("base_service:unit_mismatch_expected_person_hours", issues)
        self.assertIn("replacement_carry:person_count_positive_integer_required", issues)
        self.assertIn("operations[7]:unknown_operation_id", issues)

    def test_unknown_wait_duration_is_partial_without_losing_person_hours(self):
        scenario = approved_common_scenario_fixture()
        wait = next(row for row in scenario["operations"] if row["operation_id"] == "parts_wait")
        wait["elapsed_hours"] = None
        result = run(scenario)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["labor"]["person_hours"]["typical"], 2.13)
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})
        self.assertIn("parts_wait:elapsed_duration_unknown", result["labor"]["unknowns"])

    def test_null_or_missing_required_work_and_wait_durations_stop_pipeline(self):
        for operation_id, key in (("wash", "hours"), ("included_carry", "hours"),
                                  ("base_service", "hours")):
            for missing in (False, True):
                with self.subTest(operation_id=operation_id, key=key, missing=missing):
                    scenario = approved_common_scenario_fixture()
                    operation = next(row for row in scenario["operations"]
                                     if row["operation_id"] == operation_id)
                    if missing:
                        operation.pop(key)
                    else:
                        operation[key] = None
                    result = run(scenario)
                    self.assertEqual(result["status"], "missing-required")
                    self.assertEqual(result["labor"]["person_hours"],
                                     {"low": None, "typical": None, "high": None})
                    self.assertEqual([event["stage"] for event in result["trace"]], ["validate"])

    def test_explicit_work_expands_by_headcount_and_parallel_elapsed_stays_per_person(self):
        scenario = approved_common_scenario_fixture()
        wash = next(row for row in scenario["operations"] if row["operation_id"] == "wash")
        wash["person_count"] = 2
        result = run(scenario)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["labor"]["person_hours"],
                         {"low": 1.98, "typical": 2.23, "high": 2.48})
        self.assertEqual(result["labor"]["elapsed_hours"],
                         {"low": 2.53, "typical": 2.78, "high": 3.03})
        expanded_wash = next(row for row in result["trace"][2]["rows"]
                             if row["operation_id"] == "wash")
        self.assertEqual(expanded_wash["person_hours"], 0.2)

    def test_included_carry_null_cannot_be_silently_treated_as_zero(self):
        scenario = approved_common_scenario_fixture()
        included = next(row for row in scenario["operations"]
                        if row["operation_id"] == "included_carry")
        included["hours"] = None
        result = run(scenario)
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("included_carry:hours_required_finite_nonnegative", result["labor"]["unknowns"])

    def test_unapproved_rotor_condition_width_stops_with_null_ranges(self):
        scenario = approved_common_scenario_fixture()
        scenario["fields"]["rotor_relevance"]["value"] = "relevant"
        scenario["fields"]["rotor_seizure_hours"] = {
            "value": {"low": 0.0, "typical": 0.25, "high": 0.5},
            "status": "assumed", "source": "fictional_unapproved_width",
        }
        scenario["metadata"]["approved_condition_widths"].clear()
        result = run(scenario)
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertIn("rotor_seizure_hours:human_approval_required", result["labor"]["unknowns"])


if __name__ == "__main__":
    unittest.main()
