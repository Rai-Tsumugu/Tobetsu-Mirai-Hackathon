from copy import deepcopy
import unittest

from .contract import common_scenario_fixture
from . import e16


def previous_visit():
    return {
        "visit_id": "visit-old", "vehicle_token": "veh_fictional_001",
        "job_id": "front_brake_service",
        "observed_at": "2026-10-01T10:00:00+09:00",
        "conditions": {
            "work_scope": {"value": "front_brake_service", "status": "confirmed"},
            "included_operations": {"value": ["remove_install", "rust_observation", "snow_removal"], "status": "confirmed"},
            "rotor_relevance": {"value": "relevant", "status": "confirmed"},
            "rotor_seizure_hours": {"value": {"low": 0.0, "typical": 0.25, "high": 0.5}, "status": "confirmed"},
            "parts_wait_stock_checked": {"value": True, "status": "confirmed"},
            "snow_observation": {"value": "present", "status": "confirmed"},
        },
    }


def current_scenario():
    scenario = common_scenario_fixture()
    scenario["visit_id"] = "visit-current"
    scenario["observed_at"] = "2026-10-11T10:00:00+09:00"
    return scenario


class E16PreviousVisitExpiryTests(unittest.TestCase):
    def test_copy_preserves_scope_but_expires_every_vehicle_condition(self):
        old = previous_visit()
        snapshot = deepcopy(old)
        copied = e16.copy_previous_visit(old, "visit-current", "2026-10-11T10:00:00+09:00")
        self.assertEqual(old, snapshot)
        self.assertEqual(copied["conditions"]["work_scope"]["value"], "front_brake_service")
        self.assertEqual(copied["conditions"]["included_operations"]["status"], "confirmed")
        self.assertEqual(copied["conditions"]["rotor_relevance"]["status"], "unknown")
        self.assertEqual(copied["conditions"]["rotor_relevance"]["copied_value"], "relevant")
        self.assertIn("parts_wait_stock_checked", copied["expired_fields"])
        self.assertEqual(copied["copied_from"]["visit_id"], "visit-old")

    def test_previous_visit_without_current_confirms_stops_with_null_totals(self):
        scenario = current_scenario()
        before = deepcopy(scenario)
        result = e16.run(scenario, {"previous_visit": previous_visit()})
        self.assertEqual(scenario, before)
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertTrue(any("rotor_relevance" in item for item in result["labor"]["unknowns"]))
        self.assertIn("previous_visit_copied", [row["event"] for row in result["trace"]])

    def test_current_confirmations_restore_real_labor_and_reapprove_widths(self):
        scenario = current_scenario()
        confirms = [
            {"field": "rotor_relevance", "value": "relevant", "actor": "fictional_tech", "reason": "今訪問でローター固着を確認"},
            {"field": "rotor_seizure_hours", "value": {"low": 0.0, "typical": 0.25, "high": 0.5},
             "actor": "fictional_owner", "reason": "今訪問の条件幅を承認"},
            {"field": "subframe_relevance", "value": "unrelated", "actor": "fictional_tech", "reason": "今訪問で確認"},
            {"field": "parts_wait_stock_checked", "value": True, "actor": "fictional_tech", "reason": "今訪問で在庫確認"},
            {"field": "snow_observation", "value": "present", "actor": "fictional_tech", "reason": "今訪問で雪を確認"},
        ]
        result = e16.run(scenario, {"previous_visit": previous_visit(), "current_confirm": confirms})
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["labor"]["person_hours"]["typical"], 2.13)
        self.assertEqual(result["approvals"][1]["old_value"], None)
        self.assertEqual(result["approvals"][1]["new_value"], confirms[1]["value"])
        self.assertEqual(result["approvals"][1]["reason"], confirms[1]["reason"])

    def test_current_confirm_is_immutable_and_requires_actor_reason(self):
        original = e16.copy_previous_visit(previous_visit(), "visit-current", "2026-10-11T10:00:00+09:00")
        frozen = deepcopy(original)
        bad = e16.current_confirm(original, "rotor_relevance", "unrelated", "", "確認")
        self.assertEqual(bad["error"], "confirmation:actor_and_reason_required")
        good = e16.current_confirm(original, "rotor_relevance", "unrelated", "tech", "現車を再確認")
        self.assertIsNone(good["error"])
        self.assertEqual(original, frozen)
        self.assertEqual(good["visit"]["observations"][0]["value"], "unrelated")
        self.assertEqual(good["approval"]["old_value"], None)

    def test_expired_stock_and_snow_facts_cannot_be_reused(self):
        scenario = current_scenario()
        result = e16.run(scenario, {"previous_visit": previous_visit(), "current_confirm": [
            {"field": "rotor_relevance", "value": "unrelated", "actor": "tech", "reason": "今訪問で確認"}
        ]})
        self.assertEqual(result["status"], "missing-required")
        self.assertTrue(any("parts_wait_stock_checked" in item for item in result["labor"]["unknowns"]))
        self.assertIn("snow_observation", result["trace"][0]["expired_fields"])

    def test_invalid_visit_token_and_version_mismatch_are_controlled(self):
        with self.assertRaisesRegex(ValueError, "anonymous_vehicle_token"):
            e16.copy_previous_visit({**previous_visit(), "vehicle_token": "Jane Doe"}, "visit-current", "now")
        scenario = current_scenario()
        result = e16.run(scenario, {"rule_version": "other-v2", "previous_visit": previous_visit()})
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("rule_pack:pinned_version_mismatch", result["labor"]["unknowns"])

    def test_copy_requires_current_visit_timestamp_and_copies_job_scope(self):
        scenario = current_scenario()
        scenario.pop("observed_at")
        missing_time = e16.run(scenario, {"previous_visit": previous_visit()})
        self.assertEqual(missing_time["status"], "missing-required")
        self.assertIn("observed_at:required", missing_time["labor"]["unknowns"])

        scenario = current_scenario()
        result = e16.run(scenario, {"previous_visit": previous_visit(), "current_confirm": [
            {"field": "rotor_relevance", "value": "unrelated", "actor": "tech", "reason": "確認"},
            {"field": "subframe_relevance", "value": "unrelated", "actor": "tech", "reason": "確認"},
            {"field": "parts_wait_stock_checked", "value": True, "actor": "tech", "reason": "確認"},
            {"field": "snow_observation", "value": "present", "actor": "tech", "reason": "確認"},
        ]})
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["trace"][0]["copied_from"]["visit_id"], "visit-old")

    def test_invalid_confirmation_does_not_become_zero_or_clear_expiry(self):
        copied = e16.copy_previous_visit(previous_visit(), "visit-current", "2026-10-11T10:00:00+09:00")
        result = e16.current_confirm(copied, "rotor_seizure_hours", {"low": 0, "typical": 2, "high": 1},
                                     "tech", "bad range")
        self.assertEqual(result["error"], "confirmation:invalid_condition_range")
        self.assertEqual(result["visit"]["conditions"]["rotor_seizure_hours"]["status"], "unknown")

    def test_current_snow_observation_changes_elapsed_wait(self):
        scenario = current_scenario()

        def calculate(snow):
            confirms = [
                {"field": "rotor_relevance", "value": "unrelated", "actor": "tech", "reason": "今訪問で確認"},
                {"field": "subframe_relevance", "value": "unrelated", "actor": "tech", "reason": "今訪問で確認"},
                {"field": "parts_wait_stock_checked", "value": True, "actor": "tech", "reason": "今訪問で在庫確認"},
                {"field": "snow_observation", "value": snow, "actor": "tech", "reason": "今訪問で確認"},
            ]
            return e16.run(scenario, {"previous_visit": previous_visit(), "current_confirm": confirms})

        with_snow = calculate("present")
        without_snow = calculate("absent")
        self.assertEqual(with_snow["labor"]["elapsed_hours"]["typical"] -
                         without_snow["labor"]["elapsed_hours"]["typical"], 0.5)


if __name__ == "__main__":
    unittest.main()
