import copy
import unittest

from .contract import approved_common_scenario_fixture, common_scenario_fixture
from .e03 import DEFAULT_RULE_PACK, ENGINE_ID, parse_to_ast, run


class E03RestrictedDslTests(unittest.TestCase):
    def test_default_dsl_applies_to_human_approved_fictional_fixture(self):
        scenario = approved_common_scenario_fixture()
        result = run(scenario)
        self.assertEqual(result["engine_id"], ENGINE_ID)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["rule_version"], scenario["rule_version"])
        self.assertIn("base_service", result["operation_keys"])
        self.assertTrue(any(row["event"] == "dsl_operation_applied" for row in result["trace"]))
        base_rule = next(row for row in DEFAULT_RULE_PACK["rules"] if row["rule_id"] == "base_service")
        base_range = parse_to_ast(base_rule["expression"])["range"]
        rows = {row["operation_id"]: row for row in scenario["operations"]}
        expected_low = (base_range["low"] - rows["included_carry"]["hours"]
                        + rows["replacement_carry"]["hours_per_person"] * rows["replacement_carry"]["person_count"]
                        + scenario["fields"]["rotor_seizure_hours"]["value"]["low"] + rows["wash"]["hours"])
        self.assertEqual(result["labor"]["person_hours"]["low"], round(expected_low, 10))
        self.assertEqual(result["approvals"][0]["new_value"], scenario["fields"]["rotor_seizure_hours"]["value"])

    def test_unknown_condition_stops_common_scenario_with_null_ranges(self):
        result = run(common_scenario_fixture())
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("rotor_relevance:confirm_whether_required", result["labor"]["unknowns"])
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertTrue(all(row["status"] == "missing-required" for row in result["labor"]["breakdown"]))

    def test_rule_range_changes_computed_labor(self):
        scenario = approved_common_scenario_fixture()
        baseline = run(scenario)
        pack = copy.deepcopy(DEFAULT_RULE_PACK)
        base = next(rule for rule in pack["rules"] if rule["rule_id"] == "base_service")
        base["expression"] = 'when work_scope equals "front_brake_service" -> set_range base_service {"low":1.6,"typical":1.8,"high":2.0} person_hours'
        changed = run(scenario, pack)
        self.assertNotEqual(baseline["labor"]["person_hours"], changed["labor"]["person_hours"])
        self.assertAlmostEqual(changed["labor"]["person_hours"]["typical"] - baseline["labor"]["person_hours"]["typical"], 0.1)

    def test_parser_rejects_code_unknown_tokens_and_out_of_order_ranges(self):
        for text in (
            'when work_scope equals "front_brake_service" -> __import__("os").system("id")',
            'when arbitrary_field equals true -> set_range wash {"low":0,"typical":0,"high":0} person_hours',
            'when work_scope equals "front_brake_service" -> set_range wash {"low":2,"typical":1,"high":3} person_hours',
            'when work_scope equals "front_brake_service" -> set_range wash {"low":0,"typical":1,"high":2} exec',
        ):
            self.assertIsNone(parse_to_ast(text))

    def test_non_finite_or_negative_range_and_unknown_rule_fields_stop(self):
        scenario = approved_common_scenario_fixture()
        pack = copy.deepcopy(DEFAULT_RULE_PACK)
        pack["rules"][0]["expression"] = 'when work_scope equals "front_brake_service" -> set_range base_service {"low":0,"typical":NaN,"high":2} person_hours'
        result = run(scenario, pack)
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("rule_pack:unknown_token_or_invalid_expression:base_service", result["labor"]["unknowns"])
        pack = copy.deepcopy(DEFAULT_RULE_PACK)
        pack["rules"][0]["extra"] = "eval"
        self.assertEqual(run(scenario, pack)["status"], "missing-required")

    def test_version_pin_and_approval_width_are_preserved(self):
        scenario = approved_common_scenario_fixture()
        pack = copy.deepcopy(DEFAULT_RULE_PACK)
        pack["rule_version"] = "fictional-rule-v2"
        result = run(scenario, pack)
        self.assertIn("rule_pack:pinned_version_mismatch", result["labor"]["unknowns"])
        pack = copy.deepcopy(DEFAULT_RULE_PACK)
        pack["rules"][-1]["expression"] = 'when rotor_relevance equals "relevant" -> set_range rotor_seizure {"low":0,"typical":0.3,"high":0.5} person_hours'
        result = run(scenario, pack)
        self.assertIn("rotor_seizure:range_must_match_human_approval", result["labor"]["unknowns"])

    def test_unknown_wait_duration_stays_partial_and_known_wait_ranges_affect_elapsed_width(self):
        scenario = approved_common_scenario_fixture()
        scenario["operations"][3]["elapsed_hours"] = None
        result = run(scenario)
        snow_row = next(row for row in result["labor"]["breakdown"] if row["operation_id"] == "snow_melt")
        self.assertEqual(result["status"], "partial")
        self.assertIn("snow_melt:elapsed_duration_unknown", result["labor"]["unknowns"])
        self.assertEqual(result["labor"]["person_hours"]["typical"], 2.13)
        self.assertEqual(snow_row["hours"], {"low": 0.0, "typical": 0.0, "high": 0.0})
        self.assertEqual(snow_row["elapsed_hours"], {"low": None, "typical": None, "high": None})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})

        scenario = approved_common_scenario_fixture()
        pack = copy.deepcopy(DEFAULT_RULE_PACK)
        snow_rule = next(rule for rule in pack["rules"] if rule["rule_id"] == "snow_melt")
        snow_rule["expression"] = 'when work_scope equals "front_brake_service" -> set_range snow_melt {"low":0.4,"typical":0.5,"high":0.6} elapsed_hours'
        known = run(scenario, pack)
        self.assertEqual(known["status"], "proposed")
        self.assertEqual(known["labor"]["elapsed_hours"]["typical"], 2.78)
        self.assertEqual(known["labor"]["elapsed_hours"]["low"], 2.43)
        self.assertEqual(known["labor"]["elapsed_hours"]["high"], 3.13)

    def test_missing_raw_rule_version_stops_even_when_default_pack_is_approved(self):
        scenario = approved_common_scenario_fixture()
        pack = copy.deepcopy(DEFAULT_RULE_PACK)
        pack.pop("rule_version")
        result = run(scenario, pack)
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["rule_version"], "unbound")
        self.assertIn("rule_pack:rule_version_required", result["labor"]["unknowns"])
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})


if __name__ == "__main__":
    unittest.main()
