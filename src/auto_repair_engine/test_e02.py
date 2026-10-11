import copy
import tempfile
import unittest
from pathlib import Path

from .contract import approved_common_scenario_fixture, common_scenario_fixture
from .e02 import ENGINE_ID, run
from .store import AutoRepairStore


def approved_pack(version="fictional-rule-v1"):
    return {
        "engine_id": ENGINE_ID,
        "rule_version": version,
        "status": "approved",
        "approved_by": "fictional_shop_owner",
        "effective_from": "2026-10-11T00:00:00+00:00",
        "source": "fictional_fixture_only",
        "basis_unit": "person_hour",
        "basis_definition": "架空の整備作業範囲。含有運搬を除き、承認済み作業行を人時で集計する",
        "rules": [
            {"job_id": "front_brake_service", "operation_key": "base_service", "condition": {"field": "work_scope", "equals": "front_brake_service"}, "hours": {"low": 1.7, "typical": 1.7, "high": 1.7}, "unit": "person_hours", "source": "fictional_json:base"},
            {"job_id": "front_brake_service", "operation_key": "replacement_carry", "condition": {"field": "included_operations", "contains": "remove_install"}, "hours": {"low": 0.2, "typical": 0.2, "high": 0.2}, "unit": "person_hours", "source": "fictional_json:carry"},
            {"job_id": "front_brake_service", "operation_key": "snow_melt", "condition": {"field": "included_operations", "contains": "snow_removal"}, "hours": {"low": 0.5, "typical": 0.5, "high": 0.5}, "unit": "elapsed_hours", "source": "fictional_json:snow"},
            {"job_id": "front_brake_service", "operation_key": "penetrant_wait", "condition": {"field": "work_scope", "equals": "front_brake_service"}, "hours": {"low": 0.25, "typical": 0.25, "high": 0.25}, "unit": "elapsed_hours", "source": "fictional_json:penetrant"},
            {"job_id": "front_brake_service", "operation_key": "parts_wait", "condition": {"field": "parts_wait_stock_checked", "equals": True}, "hours": {"low": 0.0, "typical": 0.0, "high": 0.0}, "unit": "elapsed_hours", "source": "fictional_json:parts"},
            {"job_id": "front_brake_service", "operation_key": "wash", "condition": {"field": "work_scope", "equals": "front_brake_service"}, "hours": {"low": 0.1, "typical": 0.1, "high": 0.1}, "unit": "person_hours", "source": "fictional_json:wash"},
            {"job_id": "front_brake_service", "operation_key": "rotor_seizure", "condition": {"field": "rotor_relevance", "equals": "relevant"}, "hours": {"low": 0.0, "typical": 0.25, "high": 0.5}, "unit": "person_hours", "source": "fictional_json:rotor"},
        ],
    }


class E02VersionedJsonTests(unittest.TestCase):
    def test_approved_pack_keeps_canonical_fictional_labor_and_trace(self):
        result = run(approved_common_scenario_fixture(), approved_pack())
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["engine_id"], ENGINE_ID)
        self.assertEqual(result["rule_version"], "fictional-rule-v1")
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": 2.53, "typical": 2.78, "high": 3.03})
        applied = next(row for row in result["trace"] if row.get("event") == "rule_applied" and row["operation_key"] == "base_service")
        self.assertEqual(applied["rule_source"], "fictional_json:base")
        base_line = next(row for row in result["labor"]["breakdown"] if row["operation_key"] == "base_service")
        self.assertEqual(base_line["rule_version"], "fictional-rule-v1")
        self.assertTrue(result["approvals"])
        approval = next(row for row in result["approvals"] if row.get("operation_key") == "rotor_seizure")
        self.assertEqual(approval["actor"], "fictional_shop_owner")
        self.assertEqual(approval["reason"], "fictional fixture approval")
        self.assertIsNone(approval["old_value"])
        self.assertEqual(approval["new_value"], {"low": 0.0, "typical": 0.25, "high": 0.5})

    def test_missing_or_unapproved_pack_stops_with_all_null_ranges(self):
        for scenario, pack in ((common_scenario_fixture(), None),
                               (approved_common_scenario_fixture(), {**approved_pack(), "status": "proposed"}),
                               (approved_common_scenario_fixture(), {k: v for k, v in approved_pack().items() if k != "approved_by"})):
            result = run(scenario, pack)
            self.assertEqual(result["status"], "missing-required")
            self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
            self.assertEqual(result["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})
            self.assertTrue(all(set(row["hours"].values()) == {None} for row in result["labor"]["breakdown"]))

    def test_scenario_version_is_pinned_and_mismatch_cannot_replay_new_pack(self):
        scenario = approved_common_scenario_fixture()
        first = run(scenario, approved_pack("fictional-rule-v1"))
        replay = run(copy.deepcopy(scenario), approved_pack("fictional-rule-v1"))
        swapped = run(scenario, approved_pack("fictional-rule-v2"))
        self.assertEqual(first["trace"], replay["trace"])
        self.assertEqual(swapped["status"], "missing-required")
        self.assertIn("rule_pack:pinned_version_mismatch", swapped["labor"]["unknowns"])

    def test_store_keeps_old_versions_and_rejects_same_version_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AutoRepairStore(Path(temp) / "e02.sqlite3")
            v1 = approved_pack("fictional-rule-v1")
            v2 = approved_pack("fictional-rule-v2")
            store.save_rule_pack(v1)
            store.save_rule_pack(v2)
            changed_v1 = {**v1, "source": "changed"}
            with self.assertRaises(ValueError):
                store.save_rule_pack(changed_v1)
            self.assertEqual(store.get_rule_pack(ENGINE_ID, "fictional-rule-v1"), v1)
            self.assertEqual(store.get_rule_pack(ENGINE_ID, "fictional-rule-v2"), v2)

    def test_missing_required_scenario_inputs_remain_blocked(self):
        scenario = approved_common_scenario_fixture()
        scenario["fields"].pop("work_scope")
        result = run(scenario, approved_pack())
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("work_scope:required_match_and_status", result["labor"]["unknowns"])
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})

    def test_duplicate_operation_key_and_invalid_operation_key_are_rejected(self):
        for mutate, expected in (
                (lambda pack: pack["rules"].append(copy.deepcopy(pack["rules"][0])), "rule_pack:duplicate_operation_key:base_service"),
                (lambda pack: pack["rules"][0].update(operation_key="delete_everything"), "rule_pack:invalid_operation_key:'delete_everything'")):
            scenario, pack = approved_common_scenario_fixture(), approved_pack()
            mutate(pack)
            result = run(scenario, pack)
            self.assertEqual(result["status"], "missing-required")
            self.assertIn(expected, result["labor"]["unknowns"])
            self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

    def test_rule_range_drives_calculation_and_divergent_range_changes_result(self):
        scenario = approved_common_scenario_fixture()
        baseline = run(scenario, approved_pack())
        divergent_pack = approved_pack()
        base_rule = next(rule for rule in divergent_pack["rules"] if rule["operation_key"] == "base_service")
        base_rule["hours"] = {"low": 1.6, "typical": 1.8, "high": 2.0}
        divergent = run(scenario, divergent_pack)
        self.assertEqual(baseline["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(baseline["labor"]["elapsed_hours"], {"low": 2.53, "typical": 2.78, "high": 3.03})
        self.assertEqual(divergent["labor"]["person_hours"], {"low": 1.78, "typical": 2.23, "high": 2.68})
        self.assertEqual(divergent["labor"]["elapsed_hours"], {"low": 2.43, "typical": 2.88, "high": 3.33})

    def test_malformed_rotor_approval_and_unknown_scope_stop(self):
        scenario = approved_common_scenario_fixture()
        scenario["metadata"]["approved_condition_widths"]["rotor_seizure_hours"]["reason"] = " "
        result = run(scenario, approved_pack())
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("rotor_seizure:approval_actor_reason_and_matching_old_new_range_required", result["labor"]["unknowns"])
        scenario = approved_common_scenario_fixture()
        scenario["fields"]["included_operations"]["value"].append("unrecognized_scope")
        result = run(scenario, approved_pack())
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("included_operations:unknown_operation_key", result["labor"]["unknowns"])

    def test_matching_required_rule_cannot_replace_missing_scenario_operation(self):
        scenario = approved_common_scenario_fixture()
        scenario["operations"] = [op for op in scenario["operations"]
                                  if op.get("operation_id") != "wash"]
        result = run(scenario, approved_pack())
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("wash:scenario_operation_missing", result["labor"]["unknowns"])
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})

    def test_explicit_unknown_wait_duration_is_not_filled_from_json_rule(self):
        for operation_id in ("snow_melt", "penetrant_wait", "parts_wait"):
            with self.subTest(operation_id=operation_id):
                scenario = approved_common_scenario_fixture()
                operation = next(op for op in scenario["operations"]
                                 if op.get("operation_id") == operation_id)
                operation["elapsed_hours"] = None
                result = run(scenario, approved_pack())
                self.assertEqual(result["status"], "partial")
                self.assertEqual(result["labor"]["person_hours"],
                                 {"low": 1.88, "typical": 2.13, "high": 2.38})
                self.assertEqual(result["labor"]["elapsed_hours"],
                                 {"low": None, "typical": None, "high": None})
                self.assertIn(f"{operation_id}:elapsed_duration_unknown",
                              result["labor"]["unknowns"])
                wait_row = next(row for row in result["labor"]["breakdown"]
                                if row.get("operation_id") == operation_id)
                self.assertEqual(wait_row["elapsed_hours"],
                                 {"low": None, "typical": None, "high": None})

    def test_json_low_typical_high_ranges_reach_labor_outputs(self):
        scenario = approved_common_scenario_fixture()
        pack = approved_pack()
        rules = {rule["operation_key"]: rule for rule in pack["rules"]}
        rules["base_service"]["hours"] = {"low": 1.6, "typical": 1.8, "high": 2.0}
        rules["wash"]["hours"] = {"low": 0.05, "typical": 0.1, "high": 0.2}
        result = run(scenario, pack)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["labor"]["person_hours"],
                         {"low": 1.73, "typical": 2.23, "high": 2.78})
        self.assertEqual(result["labor"]["elapsed_hours"],
                         {"low": 2.38, "typical": 2.88, "high": 3.43})


if __name__ == "__main__":
    unittest.main()
