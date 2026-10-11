"""Focused behavior tests for the normalized SQLite E04 engine."""
from __future__ import annotations

import copy
import sqlite3
import unittest

from auto_repair_engine.contract import approved_common_scenario_fixture, common_scenario_fixture, validate_core_contract
from auto_repair_engine.e04 import create_database, publish_rule_pack, run, seed_default_rule_pack


def fictional_pack(version: str = "fictional-rule-v1", wash_hours: float = 0.1) -> dict:
    definitions = (
        ("base_service", "承認済み基準作業", "work", "person_hours", 1.7, 1),
        ("included_carry", "含有運搬", "work", "person_hours", 0.12, 1),
        ("replacement_carry", "二人作業の運搬", "work", "person_hours", 0.2, 2),
        ("rotor_seizure", "ローター固着", "work", "person_hours", {"low": 0, "typical": 0.25, "high": 0.5}, 1),
        ("snow_melt", "雪の融解待ち", "wait", "elapsed_hours", 0.5, 0),
        ("penetrant_wait", "浸透待ち", "wait", "elapsed_hours", 0.25, 0),
        ("parts_wait", "部品待ち", "wait", "elapsed_hours", 0.0, 0),
        ("wash", "洗浄", "work", "person_hours", wash_hours, 1),
    )
    entries = []
    for operation_id, name, kind, unit, hours, person_count in definitions:
        if isinstance(hours, (int, float)):
            hours = {"low": hours, "typical": hours, "high": hours}
        entries.append({
            "operation_id": operation_id,
            "operation_key": operation_id,
            "operation": name,
            "kind": kind,
            "unit": unit,
            "hours": hours,
            "person_count": person_count,
            "evidence": [{"source": "fictional_simulator_fixture", "note": f"架空 evidence: {operation_id}"}],
        })
    return {"id": "fictional_labor_rules", "rule_version": version, "status": "approved",
            "approved_by": "fictional_shop_owner", "effective_from": "2026-10-11",
            "source": "fictional_simulator_fixture", "rules": entries}


class E04SQLiteTests(unittest.TestCase):
    def test_default_approved_fixture_uses_sqlite_and_preserves_common_math(self):
        scenario = approved_common_scenario_fixture()
        result = run(scenario)
        labor = result["labor"]
        self.assertEqual(result["engine_id"], "e04_sqlite_normalized")
        self.assertEqual(result["rule_version"], "fictional-rule-v1")
        self.assertEqual(labor["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(labor["elapsed_hours"], {"low": 2.53, "typical": 2.78, "high": 3.03})
        self.assertEqual(validate_core_contract(labor), [])
        self.assertTrue(any(item["event"] == "rule_operation_joined" and item["operation_id"] == "wash"
                            for item in result["trace"]))
        self.assertTrue(result["approvals"])

    def test_joined_rule_values_change_labor_and_evidence_is_returned(self):
        db = create_database()
        seed_default_rule_pack(db)
        scenario = approved_common_scenario_fixture()
        original = run(scenario, connection=db)
        publish_rule_pack(db, fictional_pack("fictional-rule-v2", wash_hours=0.2))
        scenario["rule_version"] = "fictional-rule-v2"
        changed = run(scenario, connection=db)
        self.assertEqual(original["labor"]["person_hours"]["typical"], 2.13)
        self.assertEqual(changed["labor"]["person_hours"]["typical"], 2.23)
        self.assertEqual(changed["labor"]["elapsed_hours"]["typical"], 2.88)
        wash_trace = next(item for item in changed["trace"]
                          if item["event"] == "rule_operation_joined" and item["operation_id"] == "wash")
        self.assertEqual(wash_trace["hours"], {"low": 0.2, "typical": 0.2, "high": 0.2})
        self.assertEqual(wash_trace["evidence"][0]["source"], "fictional_simulator_fixture")

    def test_version_pin_replays_old_values_after_new_version_is_added(self):
        db = create_database()
        seed_default_rule_pack(db, "fictional-rule-v1")
        publish_rule_pack(db, fictional_pack("fictional-rule-v2", wash_hours=0.2))
        scenario = approved_common_scenario_fixture()
        old_result = run(scenario, connection=db)
        scenario["rule_version"] = "fictional-rule-v2"
        new_result = run(scenario, connection=db)
        self.assertEqual(old_result["labor"]["person_hours"]["typical"], 2.13)
        self.assertEqual(new_result["labor"]["person_hours"]["typical"], 2.23)
        self.assertEqual(old_result["approvals"][0]["rule_version"], "fictional-rule-v1")
        self.assertEqual(new_result["approvals"][0]["rule_version"], "fictional-rule-v2")

    def test_joined_rotor_range_must_match_scenario_and_human_approval(self):
        db = create_database()
        seed_default_rule_pack(db, "fictional-rule-v1")
        pack = fictional_pack("fictional-rule-v2")
        rotor = next(item for item in pack["rules"] if item["operation_id"] == "rotor_seizure")
        rotor["hours"] = {"low": 8.0, "typical": 8.0, "high": 8.0}
        publish_rule_pack(db, pack)
        scenario = approved_common_scenario_fixture()
        scenario["rule_version"] = "fictional-rule-v2"
        result = run(scenario, connection=db)
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("rotor_seizure_hours:rule_approval_mismatch", result["labor"]["unknowns"])
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

    def test_published_rule_and_operation_rows_reject_update_and_delete(self):
        db = create_database()
        seed_default_rule_pack(db, "fictional-rule-v1")
        statements = (
            ("UPDATE rules SET source = 'tampered' WHERE version = 'fictional-rule-v1'",),
            ("DELETE FROM rules WHERE version = 'fictional-rule-v1'",),
            ("UPDATE operations SET name = 'tampered' WHERE id = 'wash'",),
            ("DELETE FROM operations WHERE id = 'wash'",),
            ("UPDATE rule_operations SET typical = 0.9, high = 1.0 WHERE version = 'fictional-rule-v1' AND operation_id = 'wash'",),
            ("DELETE FROM rule_operations WHERE version = 'fictional-rule-v1' AND operation_id = 'wash'",),
            ("UPDATE evidence SET note = 'tampered' WHERE version = 'fictional-rule-v1' AND operation_id = 'wash'",),
            ("DELETE FROM evidence WHERE version = 'fictional-rule-v1' AND operation_id = 'wash'",),
        )
        for (statement,) in statements:
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                db.execute(statement)
        replay = run(approved_common_scenario_fixture(), connection=db)
        self.assertEqual(replay["status"], "proposed")
        self.assertEqual(replay["labor"]["person_hours"]["typical"], 2.13)
        publish_rule_pack(db, fictional_pack("fictional-rule-v2", wash_hours=0.2))

    def test_duplicate_publish_rolls_back_without_partial_rule_version(self):
        db = create_database()
        pack = fictional_pack("fictional-duplicate")
        pack["rules"].append(copy.deepcopy(pack["rules"][-1]))
        with self.assertRaisesRegex(ValueError, "duplicate operation_id"):
            publish_rule_pack(db, pack)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM rules WHERE version = ?", ("fictional-duplicate",)).fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM rule_operations WHERE version = ?", ("fictional-duplicate",)).fetchone()[0], 0)

    def test_foreign_keys_reject_orphan_rule_operation_and_evidence(self):
        db = create_database()
        seed_default_rule_pack(db)
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("INSERT INTO rule_operations(rule_id, version, operation_id, low, typical, high, person_count) "
                       "VALUES ('missing', 'v1', 'wash', 0.1, 0.1, 0.1, 1)")
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("INSERT INTO evidence(id, rule_id, version, operation_id, source, note) "
                       "VALUES ('orphan', 'fictional_labor_rules', 'fictional-rule-v1', 'missing', 'fictional', '')")

    def test_unknown_rotor_condition_stops_and_does_not_turn_null_into_zero(self):
        result = run(common_scenario_fixture())
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertIn("rotor_relevance:confirm_whether_required", result["labor"]["unknowns"])

    def test_wait_hours_are_elapsed_only_and_human_rotor_approval_is_kept(self):
        result = run(approved_common_scenario_fixture())
        waits = [row for row in result["labor"]["breakdown"] if row["status"] == "wait"]
        self.assertEqual(len(waits), 3)
        self.assertTrue(all(row["hours"] == {"low": 0.0, "typical": 0.0, "high": 0.0} for row in waits))
        self.assertEqual(sum(row["elapsed_hours"]["typical"] for row in waits), 0.75)
        approval = next(item for item in result["approvals"] if item.get("operation_key") == "rotor_seizure")
        self.assertEqual(approval["actor"], "fictional_shop_owner")
        self.assertEqual(approval["old_value"], None)
        self.assertEqual(approval["new_value"], {"low": 0.0, "typical": 0.25, "high": 0.5})

    def test_rule_pack_version_mismatch_stops(self):
        scenario = approved_common_scenario_fixture()
        result = run(scenario, fictional_pack("fictional-other-version"))
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("rule_pack:pinned_version_mismatch", result["labor"]["unknowns"])


if __name__ == "__main__":
    unittest.main()
