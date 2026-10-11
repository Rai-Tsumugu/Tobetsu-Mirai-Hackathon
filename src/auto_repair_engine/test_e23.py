import unittest
from .contract import approved_common_scenario_fixture
from .e23 import run

class E23ReferenceBucketTests(unittest.TestCase):
    def test_samples_are_grouped_with_median_range_and_sparse_reference_flag(self):
        samples = [{"sample_id": str(i), "operation_id": "wash", "unit": "person_hour", "condition": "clean", "hours": x} for i, x in enumerate((1, 2, 9))]
        result = run(approved_common_scenario_fixture(), {"samples": samples, "minimum_samples": 5})
        bucket = result["reference_report"][0]
        self.assertEqual((bucket["n"], bucket["median_hours"], bucket["range_hours"]), (3, 2, {"low": 1, "high": 9}))
        self.assertTrue(bucket["reference_only"])
        self.assertFalse(bucket["autopublished"])

    def test_invalid_unit_is_not_summarized(self):
        result = run(approved_common_scenario_fixture(), {"samples": [{"sample_id": "x", "operation_id": "wash", "unit": "points", "condition": "clean", "hours": 1}]})
        self.assertEqual(result["reference_report"], [])
        self.assertIn("samples[0]:invalid_observation", result["reference_issues"])

    def test_duplicate_sample_ids_are_rejected_before_aggregation(self):
        samples = [{"sample_id": "same", "operation_id": "wash", "unit": "person_hour", "condition": "clean", "hours": 1},
                   {"sample_id": "same", "operation_id": "wash", "unit": "person_hour", "condition": "clean", "hours": 99}]
        result = run(approved_common_scenario_fixture(), {"samples": samples})
        self.assertEqual(result["reference_report"], [])
        self.assertIn("samples[1]:duplicate_sample_id", result["reference_issues"])

if __name__ == "__main__": unittest.main()
