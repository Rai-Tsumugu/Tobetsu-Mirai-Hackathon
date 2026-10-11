"""Focused tests for E06 approval lifecycle and immutable JSON snapshots."""
from __future__ import annotations

import copy
import unittest

from .contract import approved_common_scenario_fixture, common_scenario_fixture
from .e06 import ENGINE_ID, payload_hash, publish_rule_pack, run


class E06ApprovalTests(unittest.TestCase):
    def fixture_pack(self):
        scenario = common_scenario_fixture()
        pack = {
            "engine_id": "e06_approval_rules", "rule_version": "fictional-e06-test-v1",
            "source": "fixture", "basis_unit": scenario["basis_unit"],
            "basis_definition": scenario["basis_definition"], "rules": [
                {"job_id": "front_brake_service", "operation_key": key, "condition": condition,
                 "hours": hours, "unit": unit, "source": "fixture:" + key}
                for key, condition, hours, unit in (
                    ("base_service", {"field": "work_scope", "equals": "front_brake_service"}, {"low": 1.7, "typical": 1.7, "high": 1.7}, "person_hours"),
                    ("replacement_carry", {"field": "included_operations", "contains": "remove_install"}, {"low": .2, "typical": .2, "high": .2}, "person_hours"),
                    ("snow_melt", {"field": "included_operations", "contains": "snow_removal"}, {"low": .5, "typical": .5, "high": .5}, "elapsed_hours"),
                    ("penetrant_wait", {"field": "work_scope", "equals": "front_brake_service"}, {"low": .25, "typical": .25, "high": .25}, "elapsed_hours"),
                    ("parts_wait", {"field": "parts_wait_stock_checked", "equals": True}, {"low": 0, "typical": 0, "high": 0}, "elapsed_hours"),
                    ("wash", {"field": "work_scope", "equals": "front_brake_service"}, {"low": .1, "typical": .1, "high": .1}, "person_hours"),
                    ("rotor_seizure", {"field": "rotor_relevance", "equals": "relevant"}, {"low": 0, "typical": .25, "high": .5}, "person_hours"),
                )
            ]}
        return publish_rule_pack(pack, "fictional_reviewer", "fixture rules approved",
                                 "2026-10-11", previous=None)

    def test_default_approved_fixture_and_rule_values_drive_labor(self):
        scenario = approved_common_scenario_fixture()
        result = run(scenario)
        self.assertEqual(result["engine_id"], ENGINE_ID)
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        pack = self.fixture_pack()
        changed_payload = copy.deepcopy(pack)
        changed_payload["rule_version"] = "fictional-rule-v2"
        base = next(rule for rule in changed_payload["rules"] if rule["operation_key"] == "base_service")
        base["hours"] = {"low": 1.9, "typical": 1.9, "high": 1.9}
        changed_payload.pop("payload_hash")
        changed = publish_rule_pack(changed_payload, "reviewer_2", "approved revised labor", "2026-10-11", previous=pack)
        changed_scenario = copy.deepcopy(scenario)
        changed_scenario["rule_version"] = changed["rule_version"]
        changed_scenario["rule_version"] = changed["rule_version"]
        revised = run(changed_scenario, changed)
        self.assertEqual(revised["labor"]["person_hours"]["typical"], 2.33)
        audit = next(row for row in revised["approvals"][0]["changes"] if row["operation_key"] == "base_service")
        self.assertEqual(audit["actor"], "reviewer_2")
        self.assertEqual(audit["old_value"]["hours"]["typical"], 1.7)
        self.assertEqual(audit["new_value"]["hours"]["typical"], 1.9)

    def test_draft_missing_or_tampered_pack_stops(self):
        scenario = approved_common_scenario_fixture()
        pack = self.fixture_pack()
        scenario["rule_version"] = pack["rule_version"]
        for mutate in (lambda p: p.update(status="draft"), lambda p: p.pop("payload_hash"),
                       lambda p: p["rules"][0]["hours"].update(typical=99)):
            bad = copy.deepcopy(pack)
            mutate(bad)
            result = run(scenario, bad)
            self.assertEqual(result["status"], "missing-required")
            self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        default_scenario = approved_common_scenario_fixture()
        self.assertEqual(run(default_scenario, None)["status"], "proposed")

    def test_future_effective_date_and_version_pin_are_gates(self):
        scenario = approved_common_scenario_fixture()
        pack = self.fixture_pack()
        scenario["rule_version"] = pack["rule_version"]
        future_payload = copy.deepcopy(pack)
        future_payload.pop("payload_hash")
        future_payload["rule_version"] = "fictional-e06-future-v1"
        future = publish_rule_pack(future_payload, "reviewer", "scheduled future approval", "2027-01-01", previous=pack)
        result = run(scenario, future)
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["trace"][0]["reason"], "not_yet_effective")
        wrong = copy.deepcopy(scenario)
        wrong["rule_version"] = "unpublished-v99"
        mismatch = run(wrong, pack)
        self.assertEqual(mismatch["status"], "missing-required")
        self.assertEqual(mismatch["trace"][0]["reason"], "pinned_version_mismatch")

    def test_rehashed_forgery_and_condition_only_change_are_rejected_or_audited(self):
        scenario = approved_common_scenario_fixture()
        pack = self.fixture_pack()
        scenario["rule_version"] = pack["rule_version"]
        forged = copy.deepcopy(pack)
        forged["rules"][0]["hours"] = {"low": 8, "typical": 8, "high": 8}
        forged["payload_hash"] = payload_hash(forged)
        result = run(scenario, forged)
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["trace"][0]["reason"], "published_snapshot_unregistered_or_mismatch")

        revised_payload = copy.deepcopy(pack)
        revised_payload.pop("payload_hash")
        revised_payload["rule_version"] = "fictional-e06-condition-v2"
        target = next(rule for rule in revised_payload["rules"] if rule["operation_key"] == "base_service")
        target["condition"] = {"field": "work_scope", "equals": "different_job"}
        revised = publish_rule_pack(revised_payload, "reviewer_3", "narrow rule applicability", "2026-10-11", previous=pack)
        condition_audit = next(row for row in revised["approval_audit"] if row["operation_key"] == "base_service")
        self.assertEqual(condition_audit["actor"], "reviewer_3")
        self.assertEqual(condition_audit["reason"], "narrow rule applicability")
        self.assertNotEqual(condition_audit["old_value"]["condition"], condition_audit["new_value"]["condition"])
        scenario["rule_version"] = revised["rule_version"]
        applied = run(scenario, revised)
        self.assertEqual(applied["status"], "missing-required")

    def test_publish_version_is_immutable_and_snapshot_is_defensive(self):
        pack = self.fixture_pack()
        snapshot = copy.deepcopy(pack)
        pack["rules"][0]["hours"]["typical"] = 9
        self.assertEqual(snapshot["payload_hash"], payload_hash(snapshot))
        changed = copy.deepcopy(snapshot)
        changed["rules"][0]["hours"] = {"low": 2, "typical": 2, "high": 2}
        with self.assertRaisesRegex(ValueError, "published_version_is_immutable"):
            publish_rule_pack(changed, "reviewer", "another change", "2026-10-11")

    def test_pack_level_semantic_changes_are_audited(self):
        previous = self.fixture_pack()
        revised = copy.deepcopy(previous)
        revised.pop("payload_hash")
        revised["rule_version"] = "fictional-e06-pack-attrs-v2"
        revised["source"] = "fixture:reviewed-source"
        revised["basis_definition"] = "Revised fictional person-hour basis."
        published = publish_rule_pack(revised, "reviewer_3", "clarify pack basis", "2026-10-12",
                                      previous=previous)
        changes = {row["operation_key"]: row for row in published["approval_audit"]}
        self.assertEqual(changes["@pack:source"]["old_value"], "fixture")
        self.assertEqual(changes["@pack:source"]["new_value"], "fixture:reviewed-source")
        self.assertEqual(changes["@pack:basis_definition"]["old_value"], previous["basis_definition"])
        self.assertEqual(changes["@pack:effective_from"]["old_value"], "2026-10-11")
        self.assertEqual(changes["@pack:effective_from"]["new_value"], "2026-10-12")
        self.assertTrue(all(row["actor"] == "reviewer_3" and row["reason"] == "clarify pack basis"
                            for row in changes.values()))

    def test_empty_rules_and_noncanonical_payload_stop_with_null_labor(self):
        empty = {"engine_id": ENGINE_ID, "rule_version": "fictional-e06-empty-v1", "rules": []}
        with self.assertRaisesRegex(ValueError, "nonempty_rules_required"):
            publish_rule_pack(empty, "reviewer", "reject empty rule set", "2026-10-11")

        scenario = approved_common_scenario_fixture()
        malformed = self.fixture_pack()
        malformed["rules"][0]["hours"]["typical"] = float("nan")
        malformed["payload_hash"] = "tampered"
        result = run(scenario, malformed)
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("payload_not_canonical_json", result["trace"][0]["reason"])
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})


if __name__ == "__main__":
    unittest.main()
