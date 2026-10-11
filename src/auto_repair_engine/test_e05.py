import copy
from dataclasses import replace
import unittest

from .contract import approved_common_scenario_fixture
from .e05 import (
    CSV_COLUMNS,
    ENGINE_ID,
    PublishedRulePack,
    human_publish,
    parse_csv,
    preview_diff,
    run,
    validate_units,
)


FIXTURE_CSV = """job_id,operation_key,condition_field,match_value,low,typical,high,unit,source,reason
front_brake_service,base_service,work_scope,front_brake_service,1.7,1.7,1.7,person_hours,fixture:base,base work
front_brake_service,replacement_carry,included_operations,remove_install,0.2,0.2,0.2,person_hours,fixture:carry,replacement handling
front_brake_service,snow_melt,included_operations,snow_removal,0.5,0.5,0.5,elapsed_hours,fixture:snow,wait only
front_brake_service,penetrant_wait,work_scope,front_brake_service,0.25,0.25,0.25,elapsed_hours,fixture:penetrant,wait only
front_brake_service,parts_wait,parts_wait_stock_checked,true,0,0,0,elapsed_hours,fixture:parts,stock checked wait
front_brake_service,wash,work_scope,front_brake_service,0.1,0.1,0.1,person_hours,fixture:wash,performed wash
front_brake_service,rotor_seizure,rotor_relevance,relevant,0,0.25,0.5,person_hours,fixture:rotor,condition range
"""


def publish(csv_text=FIXTURE_CSV, version="e05-test-v1", previous=None):
    return human_publish(
        parse_csv(csv_text), "fixture_reviewer", "fixture approval reason", version,
        "2026-10-11T00:00:00+00:00", "person_hour",
        "架空の整備作業範囲。含有運搬を除き、承認済み作業行を人時で集計する",
        previous,
    )


class E05CsvImportTests(unittest.TestCase):
    def test_parse_hash_validation_and_preview(self):
        batch = parse_csv(FIXTURE_CSV.encode("utf-8"))
        self.assertEqual(len(batch.hash), 64)
        self.assertEqual(batch.errors, ())
        self.assertEqual(validate_units(batch), ())
        preview = preview_diff(batch)
        self.assertEqual(preview["errors"], [])
        self.assertEqual(len(preview["changes"]), len(CSV_COLUMNS) - 3)
        self.assertEqual(preview["import_hash"], batch.hash)

    def test_invalid_rows_units_ranges_unknowns_and_duplicates_are_rejected(self):
        malformed = FIXTURE_CSV.replace(
            "1.7,1.7,1.7,person_hours,fixture:base",
            "nan,-1,2,elapsed_hours,fixture:base",
        ).replace("front_brake_service,wash,", "front_brake_service,mystery_step,")
        batch = parse_csv(malformed)
        errors = validate_units(batch)
        self.assertTrue(any("invalid_numeric_range" in error for error in batch.errors))
        self.assertTrue(any("unknown_operation_key:mystery_step" in error for error in errors))
        with self.assertRaisesRegex(ValueError, "validation_failed"):
            publish(malformed, "e05-invalid-v1")

        wrong_unit = FIXTURE_CSV.replace(
            "0.5,0.5,0.5,elapsed_hours,fixture:snow",
            "0.5,0.5,0.5,person_hours,fixture:snow",
        )
        self.assertTrue(any("unit_mismatch:snow_melt" in error
                            for error in validate_units(parse_csv(wrong_unit))))

        duplicate = FIXTURE_CSV + "front_brake_service,wash,work_scope,front_brake_service,0.1,0.1,0.1,person_hours,fixture:wash2,duplicate\n"
        self.assertTrue(any("duplicate_operation_key:wash" in error for error in validate_units(parse_csv(duplicate))))

    def test_publish_requires_actor_and_reason_and_keeps_version_immutable(self):
        batch = parse_csv(FIXTURE_CSV)
        with self.assertRaisesRegex(ValueError, "actor_required"):
            human_publish(batch, " ", "reason", "e05-approval-test-v1", "today", "person_hour", "fixture")
        with self.assertRaisesRegex(ValueError, "reason_required"):
            human_publish(batch, "reviewer", " ", "e05-approval-test-v1", "today", "person_hour", "fixture")
        original = publish(version="e05-immutable-test-v1")
        changed_csv = FIXTURE_CSV.replace("1.7,1.7,1.7", "1.8,1.8,1.8")
        with self.assertRaisesRegex(ValueError, "published_version_is_immutable"):
            publish(changed_csv, version=original.rule_version)
        self.assertIsInstance(original, PublishedRulePack)

    def test_published_csv_drives_labor_and_old_snapshot_replays_unchanged(self):
        scenario = approved_common_scenario_fixture()
        baseline_pack = publish(version="e05-baseline-test-v1")
        scenario["rule_version"] = baseline_pack.rule_version
        baseline = run(scenario, baseline_pack)
        self.assertEqual(baseline["engine_id"], ENGINE_ID)
        self.assertEqual(baseline["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(baseline["labor"]["elapsed_hours"], {"low": 2.53, "typical": 2.78, "high": 3.03})
        self.assertEqual(baseline["approvals"][0]["actor"], "fixture_reviewer")
        self.assertEqual(baseline["approvals"][0]["reason"], "fixture approval reason")

        changed_csv = FIXTURE_CSV.replace("1.7,1.7,1.7", "2.0,2.0,2.0")
        next_pack = publish(changed_csv, "e05-changed-test-v1", previous=baseline_pack)
        replay = run(copy.deepcopy(scenario), baseline_pack)
        changed_scenario = copy.deepcopy(scenario)
        changed_scenario["rule_version"] = next_pack.rule_version
        changed = run(changed_scenario, next_pack)
        self.assertEqual(replay["labor"], baseline["labor"])
        self.assertEqual(changed["labor"]["person_hours"], {"low": 2.18, "typical": 2.43, "high": 2.68})
        self.assertEqual(changed["labor"]["elapsed_hours"], {"low": 2.83, "typical": 3.08, "high": 3.33})
        base_change = next(item for item in changed["approvals"][0]["changes"]
                           if item["operation_key"] == "base_service")
        self.assertEqual(base_change["old_value"]["hours"], {"low": 1.7, "typical": 1.7, "high": 1.7})
        self.assertEqual(base_change["new_value"]["hours"], {"low": 2.0, "typical": 2.0, "high": 2.0})

    def test_preview_and_publish_audit_capture_all_rule_attribute_changes(self):
        baseline = publish(version="e05-attr-base-test-v1")
        changed_csv = FIXTURE_CSV.replace("front_brake_service,base_service,work_scope,front_brake_service,",
                                          "other,base_service,work_scope,front_brake_service,")
        batch = parse_csv(changed_csv)
        preview = preview_diff(batch, baseline)
        change = next(item for item in preview["changes"] if item["operation_key"] == "base_service")
        self.assertEqual(change["old_value"]["job_id"], "front_brake_service")
        self.assertEqual(change["new_value"]["job_id"], "other")
        changed = publish(changed_csv, version="e05-attr-next-test-v1", previous=baseline)
        audit = next(item for item in changed.audit if item.operation_key == "base_service")
        self.assertEqual(audit.old_value["job_id"], "front_brake_service")
        self.assertEqual(audit.new_value["job_id"], "other")

        source_csv = FIXTURE_CSV.replace("fixture:base", "fixture:base-v2")
        source_preview = preview_diff(parse_csv(source_csv), baseline)
        source_change = next(item for item in source_preview["changes"] if item["operation_key"] == "base_service")
        self.assertEqual(source_change["old_value"]["source"], "fixture:base")
        self.assertEqual(source_change["new_value"]["source"], "fixture:base-v2")

    def test_rule_version_mismatch_is_gated_before_snapshot_application(self):
        scenario = approved_common_scenario_fixture()
        pack = publish(version="e05-version-gate-test-v1")
        scenario["rule_version"] = "different-version"
        result = run(scenario, pack)
        self.assertEqual(result["status"], "missing-required")
        self.assertFalse(any(event["event"] == "rule_applied" for event in result["trace"]))
        self.assertFalse(any(item.get("type") == "csv_publish" for item in result["approvals"]))
        self.assertTrue(any(event.get("reason") == "pinned_version_mismatch" for event in result["trace"]))

    def test_forged_pack_instance_without_valid_snapshot_and_audit_is_rejected(self):
        scenario = approved_common_scenario_fixture()
        valid = publish(version="e05-forged-pack-test-v1")
        forged = replace(valid, import_hash="f" * 64, snapshot_hash="a" * 64, audit=())
        scenario["rule_version"] = forged.rule_version

        result = run(scenario, forged)

        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["labor"]["person_hours"],
                         {"low": None, "typical": None, "high": None})
        self.assertFalse(any(event["event"] == "rule_applied" for event in result["trace"]))
        self.assertFalse(any(item.get("type") == "csv_publish" for item in result["approvals"]))
        rejected = next(event for event in result["trace"] if event["event"] == "csv_import_rejected")
        self.assertEqual(rejected["reason"], "published_pack_integrity_failed")
        self.assertIn("published_pack:required_approval_audit_missing", rejected["errors"])

    def test_non_boolean_condition_is_rejected(self):
        invalid = FIXTURE_CSV.replace("parts_wait_stock_checked,true,", "parts_wait_stock_checked,perhaps,")
        errors = validate_units(parse_csv(invalid))
        self.assertTrue(any("invalid_boolean_condition" in error for error in errors))
        with self.assertRaisesRegex(ValueError, "invalid_boolean_condition"):
            publish(invalid, version="e05-invalid-boolean-test-v1")

    def test_wait_remains_elapsed_only_and_missing_pack_stops(self):
        scenario = approved_common_scenario_fixture()
        result = run(scenario)
        waits = [row for row in result["labor"]["breakdown"] if row["status"] == "wait"]
        self.assertTrue(all(row["hours"] == {"low": 0.0, "typical": 0.0, "high": 0.0} for row in waits))
        self.assertEqual(result["labor"]["elapsed_hours"]["typical"], 2.78)

        unsupported = run(scenario, {})
        self.assertEqual(unsupported["status"], "missing-required")
        self.assertEqual(unsupported["labor"]["person_hours"], {"low": None, "typical": None, "high": None})


if __name__ == "__main__":
    unittest.main()
