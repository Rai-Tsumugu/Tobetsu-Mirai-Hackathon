"""Behavior checks for schema-driven condition intake (all values fictional)."""
from copy import deepcopy
import unittest

from .contract import approved_common_scenario_fixture, common_scenario_fixture
from . import e13


def answer(value, actor="fictional_owner", source="fictional_observation", confirmed_at="2026-10-11T00:00:00+00:00"):
    return {"value": value, "confirmed": True, "actor": actor, "source": source, "confirmed_at": confirmed_at}


class E13SchemaFormTests(unittest.TestCase):
    def test_fixture_uses_schema_and_passes_common_calculation(self):
        scenario = approved_common_scenario_fixture()
        result = e13.run(scenario)
        self.assertEqual(result["engine_id"], e13.ENGINE_ID)
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        form = next(row for row in result["trace"] if row["stage"] == "schema_form")
        self.assertEqual(form["questions"], [])
        self.assertIn("rotor_seizure_hours", form["provenance"])

    def test_missing_required_observation_returns_questions_and_null_totals(self):
        scenario = common_scenario_fixture()
        scenario["fields"].pop("subframe_relevance")
        result = e13.run(scenario)
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        form = next(row for row in result["trace"] if row["stage"] == "schema_form")
        self.assertIn("subframe_relevance", [q["field"] for q in form["questions"]])

    def test_dynamic_required_and_choice_validation(self):
        scenario = common_scenario_fixture()
        scenario["fields"]["rotor_relevance"] = {"value": None, "status": "unknown"}
        self.assertNotIn("rotor_seizure_hours", [q["field"] for q in e13.render_form(scenario)["questions"]])
        adopted = e13.apply_answers(scenario, {"rotor_relevance": answer("relevant")})
        self.assertEqual(adopted["errors"], [])
        self.assertIn("rotor_seizure_hours", [q["field"] for q in e13.render_form(adopted["scenario_input"])["questions"]])
        invalid = e13.apply_answers(scenario, {"rotor_relevance": answer("maybe")})
        self.assertIn("rotor_relevance:choice_or_value_invalid", invalid["errors"])

    def test_confirmation_provenance_is_mandatory_and_changes_calculation(self):
        original = common_scenario_fixture()
        original["fields"]["rotor_relevance"] = {"value": None, "status": "unknown"}
        selected = e13.apply_answers(original, {"rotor_relevance": answer("relevant")})
        self.assertEqual(selected["errors"], [])
        width = {"low": 0.0, "typical": 0.25, "high": 0.5}
        no_provenance = e13.apply_answers(selected["scenario_input"], {"rotor_seizure_hours": {"value": width, "confirmed": True}})
        self.assertTrue(any("explicit_confirmation" in err for err in no_provenance["errors"]))
        confirmed = e13.apply_answers(selected["scenario_input"], {"rotor_seizure_hours": answer(width)})
        self.assertEqual(confirmed["errors"], [])
        baseline = deepcopy(original)
        baseline["fields"]["rotor_relevance"] = {"value": "unrelated", "status": "confirmed", "source": "fictional observation", "confirmed_at": "2026-10-11T00:00:00+00:00"}
        before = e13.run(baseline)
        after = e13.run(confirmed["scenario_input"])
        self.assertEqual(after["labor"]["person_hours"]["high"], 2.38)
        self.assertGreater(after["labor"]["person_hours"]["high"], before["labor"]["person_hours"]["high"])
        self.assertEqual(original["fields"]["rotor_relevance"]["status"], "unknown")

    def test_batch_answers_are_order_independent_for_conditionals(self):
        scenario = common_scenario_fixture()
        width = {"low": 0.0, "typical": 0.25, "high": 0.5}
        rotor = answer(width)
        relevance = answer("relevant")
        forward = e13.apply_answers(scenario, {"rotor_relevance": relevance, "rotor_seizure_hours": rotor})
        reverse = e13.apply_answers(scenario, {"rotor_seizure_hours": rotor, "rotor_relevance": relevance})
        self.assertEqual(forward["errors"], [])
        self.assertEqual(reverse["errors"], [])
        self.assertEqual(e13.run(forward["scenario_input"])["labor"], e13.run(reverse["scenario_input"])["labor"])
        self.assertEqual(len(reverse["approvals"]), 2)
        self.assertIn("approved_condition_widths", reverse["scenario_input"]["metadata"])

    def test_unknown_batch_answer_requires_same_explicit_audit(self):
        scenario = common_scenario_fixture()
        invalid = e13.apply_answers(scenario, {"rotor_relevance": {"value": "unknown", "status": "unknown"}})
        self.assertIn("rotor_relevance:explicit_confirmation_actor_source_date_required", invalid["errors"])

    def test_explicit_unknown_is_retained_and_never_calculated_as_zero(self):
        scenario = common_scenario_fixture()
        updated = e13.apply_answers(scenario, {"rotor_relevance": {"value": "unknown", "status": "unknown",
                                                                     "confirmed": True, "actor": "reviewer",
                                                                     "source": "inspection", "confirmed_at": "2026-10-11"}})
        self.assertEqual(updated["errors"], [])
        self.assertEqual(updated["scenario_input"]["fields"]["rotor_relevance"]["status"], "unknown")
        result = e13.run(updated["scenario_input"])
        self.assertIn("rotor_relevance:unknown_confirmation_required", result["labor"]["unknowns"])
        self.assertIsNone(result["labor"]["person_hours"]["typical"])

    def test_answers_do_not_mutate_input_and_job_schema_can_be_overridden(self):
        scenario = common_scenario_fixture()
        original = deepcopy(scenario)
        result = e13.apply_answers(scenario, {"parts_wait_stock_checked": answer(False)})
        self.assertEqual(scenario, original)
        self.assertEqual(result["scenario_input"]["fields"]["parts_wait_stock_checked"]["value"], False)
        schema = e13.build_schema("fictional_job", {"form_schemas": {"fictional_job": [{"field": "f", "choices": ["x"]}]}, "schema_version": "pack-v2"})
        self.assertEqual(schema["fields"][0]["field"], "f")


if __name__ == "__main__":
    unittest.main()
