import unittest
from .contract import approved_common_scenario_fixture
from .e21 import run

class E21EvidenceAdditionTests(unittest.TestCase):
    def test_approved_evidence_addition_changes_person_hours(self):
        addition = {"operation_id": "extra_inspection", "hours": 0.3, "unit": "person_hour", "source": "fictional_observation", "approval": {"actor": "fixture_owner", "reason": "observed extra work", "old_value": None, "new_value": {"hours": 0.3, "unit": "person_hour", "source": "fictional_observation"}, "rule_version": "e21-evidence-additions-v1"}}
        result = run(approved_common_scenario_fixture(), {"additions": [addition]})
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["labor"]["person_hours"]["typical"], 2.43)
        self.assertEqual(result["labor"]["breakdown"][-1]["status"], "conditional")

    def test_unapproved_or_unsourced_evidence_stops_null(self):
        result = run(approved_common_scenario_fixture(), {"additions": [{"operation_id": "x", "hours": 0.3, "unit": "person_hour"}]})
        self.assertEqual(result["status"], "missing-required")
        self.assertIsNone(result["labor"]["person_hours"]["typical"])

    def test_mismatched_old_value_and_incomplete_approval_record_are_rejected(self):
        addition = {"operation_id": "extra_inspection", "hours": 0.3, "unit": "person_hour", "source": "fictional_observation", "approval": {"actor": "fixture_owner", "reason": "observed extra work", "old_value": "nonsense", "new_value": {"hours": 0.3, "unit": "person_hour", "source": "fictional_observation"}, "rule_version": "e21-evidence-additions-v1"}}
        result = run(approved_common_scenario_fixture(), {"additions": [addition]})
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("addition[0]:effective_approval_required", result["evidence_additions"]["issues"])
        self.assertIsNone(result["labor"]["person_hours"]["typical"])

if __name__ == "__main__": unittest.main()
