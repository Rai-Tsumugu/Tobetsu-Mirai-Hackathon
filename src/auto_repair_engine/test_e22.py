import unittest
from .contract import approved_common_scenario_fixture
from .e22 import run

class E22ActualJoinTests(unittest.TestCase):
    def test_actual_delta_counts_person_work_and_excludes_wait(self):
        scenario = approved_common_scenario_fixture()
        actual = [{"operation_id": "base_service", "unit": "person_hour", "person_count": 1, "duration_hours": 2.2}, {"unit": "elapsed_hours", "is_wait": True, "duration_hours": 8}]
        result = run(scenario, {"scope_id": scenario["job_id"], "rule_version": scenario["rule_version"], "actual_steps": actual})
        self.assertTrue(result["actual_comparison"]["incomplete"])
        self.assertIsNone(result["actual_comparison"]["actual_person_hours"])
        self.assertEqual(result["actual_comparison"]["actual_steps"][-1]["excluded"], "waiting_time")

    def test_scope_or_version_mismatch_stays_incomplete(self):
        scenario = approved_common_scenario_fixture()
        result = run(scenario, {"scope_id": "other", "rule_version": "old", "actual_steps": []})
        self.assertEqual(result["actual_comparison"]["issues"], ["scope_id:estimate_actual_mismatch", "rule_version:estimate_actual_mismatch"])

    def test_complete_join_reports_person_hour_delta(self):
        scenario = approved_common_scenario_fixture()
        steps = [{"operation_id": key, "unit": "person_hour", "person_count": 1, "duration_hours": 0.5}
                 for key in ("base_service", "included_carry", "replacement_carry", "rotor_seizure", "wash")]
        result = run(scenario, {"scope_id": scenario["job_id"], "rule_version": scenario["rule_version"], "actual_steps": steps})
        self.assertTrue(result["actual_comparison"]["complete"])
        self.assertEqual(result["actual_comparison"]["actual_person_hours"], 2.5)
        self.assertEqual(result["actual_comparison"]["delta_actual_minus_estimate"], 0.37)

    def test_extra_actual_operation_id_makes_join_incomplete(self):
        scenario = approved_common_scenario_fixture()
        keys = ("base_service", "included_carry", "replacement_carry", "rotor_seizure", "wash", "extra")
        steps = [{"operation_id": key, "unit": "person_hour", "person_count": 1, "duration_hours": 99 if key == "extra" else 0.5} for key in keys]
        result = run(scenario, {"scope_id": scenario["job_id"], "rule_version": scenario["rule_version"], "actual_steps": steps})
        self.assertFalse(result["actual_comparison"]["complete"])
        self.assertIsNone(result["actual_comparison"]["actual_person_hours"])
        self.assertIn("actual_step:unknown_operation_id:extra", result["actual_comparison"]["unknowns"])

if __name__ == "__main__": unittest.main()
