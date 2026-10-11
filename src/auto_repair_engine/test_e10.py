"""Behavior and audit tests for E10's exclusive/deduplication ledger."""
from copy import deepcopy
import unittest

from .contract import approved_common_scenario_fixture, common_scenario_fixture
from .e10 import ENGINE_ID, deduct_once, replace_once, run


class E10LedgerTests(unittest.TestCase):
    def test_gross_comparison_fixture_deducts_overlap_once_and_matches_shared_totals(self):
        scenario = approved_common_scenario_fixture()
        original = deepcopy(scenario)
        result = run(scenario)
        self.assertEqual(scenario, original)
        self.assertEqual(result["engine_id"], ENGINE_ID)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": 2.53, "typical": 2.78, "high": 3.03})
        ledger = result["trace"][-1]["ledger"]
        shared = next(entry for entry in ledger["entries"] if entry["operation"] == "shared_overlap")
        self.assertEqual(shared["owners"], ["left_work", "right_work"])
        self.assertTrue(shared["deducted"])
        self.assertEqual(shared["deducted_hours"], 0.3)
        self.assertTrue(result["trace"][-1]["fixture_gross_adapter"])
        self.assertEqual(result["trace"][-1]["input_hours_ignored"], 1.7)

    def test_public_deduction_is_immutable_and_repeated_key_is_rejected(self):
        original = {"entries": []}
        key = ("shared_operation", "both", "front_brake_service")
        once, audit = deduct_once(original, key, 0.3, owners=["left", "right"], reason="shared once")
        twice, repeat = deduct_once(once, key, 0.3, owners=["third"], reason="attempt again")
        self.assertEqual(original, {"entries": []})
        self.assertTrue(audit["accepted"])
        self.assertFalse(repeat["accepted"])
        self.assertEqual(repeat["reason"], "already_deducted")
        self.assertEqual(twice, once)
        self.assertEqual(once["entries"][0]["owners"], ["left", "right"])

    def test_side_and_scope_are_part_of_deduplication_identity(self):
        ledger = {"entries": []}
        ledger, _ = deduct_once(ledger, ("align", "left", "front"), 0.1, owners="left-tech", reason="left")
        ledger, _ = deduct_once(ledger, ("align", "right", "front"), 0.1, owners="right-tech", reason="right")
        ledger, _ = deduct_once(ledger, ("align", "left", "rear"), 0.1, owners="rear-tech", reason="rear")
        self.assertEqual(len(ledger["entries"]), 3)

    def test_replacement_removes_included_work_and_cannot_be_applied_twice(self):
        source = {"operation": "included_carry", "side": "both", "scope": "front"}
        target = {"operation": "replacement_carry", "side": "both", "scope": "front"}
        ledger, _ = deduct_once({"entries": []}, source, 0.12, owners="base_service", reason="included")
        replaced, event = replace_once(ledger, source, target, owners="replacement_carry",
                                       old_hours=0.12, replacement_hours=0.2, reason="two-person replacement")
        again, repeated = replace_once(replaced, source, target, owners="replacement_carry",
                                       old_hours=0.12, replacement_hours=0.2, reason="duplicate")
        old = replaced["entries"][0]
        self.assertTrue(event["accepted"])
        self.assertFalse(repeated["accepted"])
        self.assertEqual(repeated["reason"], "already_replaced")
        self.assertEqual(again, replaced)
        self.assertEqual(old["replaced_by"], list(("replacement_carry", "both", "front")))
        self.assertEqual(old["deducted_hours"], 0.12)
        self.assertEqual(replaced["entries"][1]["replacement_hours"], 0.2)

    def test_explicit_re_deduction_of_deduplicated_fixture_stops(self):
        scenario = common_scenario_fixture()
        scenario["ledger_mode"] = "gross"
        result = run(scenario)
        self.assertEqual(result["status"], "missing-required")
        self.assertTrue(any("explicit_rededuction" in issue for issue in result["labor"]["unknowns"]))
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

    def test_custom_deduplicated_input_does_not_reapply_shared_deduction(self):
        scenario = approved_common_scenario_fixture()
        scenario["ledger_mode"] = "deduplicated"
        result = run(scenario)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(result["trace"][-1]["deduction_total_hours"], 0.0)

    def test_multiple_actions_for_same_key_are_rejected(self):
        scenario = approved_common_scenario_fixture()
        pack = {"rule_version": scenario["rule_version"], "shared_deductions": [
            {"key": ["shared_overlap", "both", "front_brake_service"], "hours": 0.3,
             "owners": ["left", "right"], "reason": "one shared operation"},
            {"key": ["shared_overlap", "both", "front_brake_service"], "hours": 0.3,
             "owners": ["left", "right"], "reason": "repeated request"},
        ]}
        result = run(scenario, pack)
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("already_deducted", " ".join(result["labor"]["unknowns"]))

    def test_exclusive_group_requires_exactly_one_selected_option(self):
        scenario = approved_common_scenario_fixture()
        result = run(scenario, {"rule_version": scenario["rule_version"],
                                "exclusive_groups": [{"name": "carry-choice", "selected": ["included", "replacement"]}]})
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("exactly_one_selection_required", " ".join(result["labor"]["unknowns"]))

    def test_unknown_wait_keeps_worker_hours_and_nulls_only_elapsed(self):
        scenario = approved_common_scenario_fixture()
        next(op for op in scenario["operations"] if op["operation_id"] == "snow_melt")["elapsed_hours"] = None
        result = run(scenario)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})
        self.assertIn("snow_melt:elapsed_duration_unknown", result["labor"]["unknowns"])

    def test_empty_explicit_rule_pack_is_not_replaced_by_default(self):
        scenario = approved_common_scenario_fixture()
        result = run(scenario, {})
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("rule_version_mismatch", " ".join(result["labor"]["unknowns"]))

    def test_malformed_explicit_ledger_returns_controlled_missing_result(self):
        scenario = approved_common_scenario_fixture()
        pack = {"rule_version": scenario["rule_version"],
                "ledger": {"entries": [{"operation": "x"}]}}
        result = run(scenario, pack)
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("ledger:key_parts_required", result["labor"]["unknowns"])
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})

    def test_missing_required_scope_stops_and_unknown_rotor_is_not_zeroed(self):
        scenario = approved_common_scenario_fixture()
        scenario["fields"]["included_operations"]["value"] = None
        missing_scope = run(scenario)
        self.assertEqual(missing_scope["status"], "missing-required")
        scenario = common_scenario_fixture()
        unknown_rotor = run(scenario)
        self.assertEqual(unknown_rotor["status"], "missing-required")
        self.assertTrue(any("rotor" in item for item in unknown_rotor["labor"]["unknowns"]))
        self.assertEqual(unknown_rotor["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})


if __name__ == "__main__":
    unittest.main()
