import unittest
import copy
from unittest.mock import patch

from .contract import approved_common_scenario_fixture, common_scenario_fixture
from . import e01
from .e01 import TABLE_VERSION, run


class E01StaticTableTests(unittest.TestCase):
    def test_unapproved_rotor_width_blocks_with_null_ranges(self):
        result = run(common_scenario_fixture())
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertIn("rotor_relevance:confirm_whether_required", result["labor"]["unknowns"])
        self.assertTrue(all(row["status"] == "missing-required" for row in result["labor"]["breakdown"]))
        self.assertTrue(any(x["event"] == "row_applied" for x in result["trace"]))
        self.assertEqual(result["table_version"], "e01-static-table-v1")

    def test_approved_fixture_substitutes_carry_and_preserves_wait_and_wash(self):
        result = run(approved_common_scenario_fixture())
        self.assertEqual(result["status"], "proposed")
        labor = result["labor"]
        self.assertEqual(labor["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(labor["elapsed_hours"], {"low": 2.53, "typical": 2.78, "high": 3.03})
        by_key = {row["operation_key"]: row for row in labor["breakdown"]}
        self.assertNotIn("included_carry", by_key)
        self.assertEqual(by_key["replacement_carry"]["hours"], {"low": 0.2, "typical": 0.2, "high": 0.2})
        self.assertEqual(by_key["snow_melt"]["hours"], {"low": 0.0, "typical": 0.0, "high": 0.0})
        self.assertEqual(by_key["wash"]["status"], "nonbillable-work")
        self.assertIn("base_service", result["operation_keys"])
        self.assertEqual(result["rule_version"], "fictional-rule-v1")
        applied = next(x for x in result["trace"] if x.get("event") == "row_applied" and x["field_key"] == "work_scope")
        self.assertEqual(applied["observation_source"], "fictional_fixture")
        self.assertEqual(applied["observation_status"], "confirmed")
        self.assertEqual(applied["confirmed_at"], "2026-10-11T00:00:00+00:00")
        self.assertEqual(applied["static_table_source"], "fictional_static_table:E01/base")

    def test_scope_missing_mismatch_or_unknown_status_stops(self):
        for mutate in (
            lambda fields: fields.pop("work_scope"),
            lambda fields: fields["work_scope"].update(value="unrelated_scope"),
            lambda fields: fields["work_scope"].update(status="unknown"),
        ):
            scenario = approved_common_scenario_fixture()
            mutate(scenario["fields"])
            result = run(scenario)
            self.assertEqual(result["status"], "missing-required")
            self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

    def test_declared_included_operation_without_table_row_stops(self):
        scenario = approved_common_scenario_fixture()
        scenario["fields"]["included_operations"]["value"].append("unmodeled_billable_operation")
        result = run(scenario)
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("included_operations:declared_operation_missing_static_table_row", result["labor"]["unknowns"])
        self.assertTrue(all(all(v is None for v in row["hours"].values()) for row in result["labor"]["breakdown"]))

    def test_unknown_rotor_relevance_status_stops(self):
        scenario = approved_common_scenario_fixture()
        scenario["fields"]["rotor_relevance"]["status"] = "unknown"
        result = run(scenario)
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})

    def test_unknown_wait_duration_keeps_person_hours_and_returns_partial(self):
        scenario = approved_common_scenario_fixture()
        next(op for op in scenario["operations"] if op["operation_id"] == "snow_melt")["elapsed_hours"] = None
        result = run(scenario)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})
        self.assertIn("snow_melt:elapsed_duration_unknown", result["labor"]["unknowns"])
        wait = next(row for row in result["labor"]["breakdown"] if row["operation_key"] == "snow_melt")
        self.assertEqual(wait["hours"], {"low": 0.0, "typical": 0.0, "high": 0.0})
        self.assertEqual(wait["elapsed_hours"], {"low": None, "typical": None, "high": None})

    def test_table_version_is_reproducible_and_unbound_rule_pack_rejected(self):
        scenario = approved_common_scenario_fixture()
        first = run(scenario)
        second = run(copy.deepcopy(scenario))
        self.assertEqual(first["table_version"], second["table_version"])
        self.assertEqual(first["trace"], second["trace"])
        rejected = run(scenario, {"rule_version": "custom-v2"})
        self.assertEqual(rejected["status"], "missing-required")
        self.assertIn("rule_pack:unbound_to_static_table_version", rejected["labor"]["unknowns"])
        dynamic = run(scenario, {"table_version": TABLE_VERSION, "rules": [{"operation": "wash"}]})
        self.assertEqual(dynamic["status"], "missing-required")
        self.assertIn("rule_pack:dynamic_rules_unsupported", dynamic["labor"]["unknowns"])
        bound_empty = run(scenario, {"table_version": TABLE_VERSION, "rules": []})
        self.assertEqual(bound_empty["status"], "proposed")

    def test_parts_wait_requires_confirmed_true_field_even_when_operation_says_stock_checked(self):
        for field_value in (None, False,
                            {"value": True, "status": "unknown", "source": "fictional_fixture", "confirmed_at": None},
                            {"value": True, "status": "declared", "source": "fictional_fixture", "confirmed_at": None}):
            scenario = approved_common_scenario_fixture()
            if field_value is None:
                scenario["fields"].pop("parts_wait_stock_checked", None)
            elif isinstance(field_value, dict):
                scenario["fields"]["parts_wait_stock_checked"] = field_value
            else:
                scenario["fields"]["parts_wait_stock_checked"] = {"value": False, "status": "confirmed", "source": "fictional_fixture", "confirmed_at": "2026-10-11T00:00:00+00:00"}
            self.assertTrue(next(op for op in scenario["operations"] if op["operation_id"] == "parts_wait")["stock_checked"])
            result = run(scenario)
            self.assertEqual(result["status"], "missing-required")
            self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

    def test_operation_without_matching_table_row_is_excluded_and_stops(self):
        scenario = approved_common_scenario_fixture()
        original_table = e01.STATIC_TABLE
        with patch.object(e01, "STATIC_TABLE", tuple(row for row in original_table if row.operation_key != "wash")):
            result = run(scenario)
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("wash:static_table_row_not_matched", result["labor"]["unknowns"])
        self.assertNotIn("wash", [row["operation_key"] for row in result["labor"]["breakdown"]])
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

    def test_unknown_job_is_blocked(self):
        result = run({"job_id": "not-in-table", "fields": {}})
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("job_id:unsupported_by_static_table", result["labor"]["unknowns"])


if __name__ == "__main__":
    unittest.main()
