from __future__ import annotations

import unittest
from copy import deepcopy

from .fixtures import demo_inputs
from .p22 import answers_to_inputs, question_guide


class QuestionGuideTests(unittest.TestCase):
    def test_missing_required_values_are_questions_and_block_calculation(self):
        inputs = demo_inputs()
        inputs["labor"]["unknowns"] = ["錆の状態が未確認"]
        inputs_before = deepcopy(inputs)

        result = question_guide(inputs, ["vehicle.color", "labor.person_hours.typical"])

        fields = {question["field"] for question in result["questions"]}
        self.assertIn("labor.unknowns", fields)
        self.assertIn("vehicle.color", fields)
        self.assertEqual(len(fields), len(result["questions"]))
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["can_calculate"])
        self.assertEqual(inputs, inputs_before)
        self.assertTrue(all({"field", "prompt", "answer", "status", "source_ref"} <= question.keys()
                            for question in result["questions"]))

    def test_conditional_approval_covers_only_named_path(self):
        inputs = demo_inputs()
        inputs["labor"]["unknowns"] = ["錆の状態"]
        inputs["conditional_approval"] = {
            "approved_by": "manager-demo",
            "reason": "錆の可能性を条件として提示",
            "fields": ["labor.unknowns"],
            "range": {"low": 1000, "typical": 1500, "high": 2500},
        }

        result = question_guide(inputs, ["vehicle.color"])

        questions = {question["field"]: question for question in result["questions"]}
        self.assertEqual(questions["labor.unknowns"]["status"], "conditional")
        self.assertEqual(questions["labor.unknowns"]["conditional_approval"]["range"]["high"], 2500)
        self.assertEqual(questions["vehicle.color"]["status"], "unanswered")
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["can_calculate"])

    def test_valid_approval_allows_only_a_conditional_calculation(self):
        inputs = demo_inputs()
        inputs["labor"]["unknowns"] = ["錆の状態"]
        inputs["conditional_approval"] = {
            "approved_by": "manager-demo",
            "reason": "錆の可能性を条件として提示",
            "fields": ["labor.unknowns"],
            "range": {"low": 1000, "typical": 1500, "high": 2500},
        }

        result = question_guide(inputs)

        self.assertEqual(result["status"], "conditional")
        self.assertTrue(result["can_calculate"])
        self.assertEqual(result["questions"][0]["answer"], ["錆の状態"])

    def test_invalid_approval_does_not_authorize_unresolved_conditions(self):
        cases = [
            {"approved_by": "", "reason": "理由", "fields": ["labor.unknowns"],
             "range": {"low": 1, "typical": 2, "high": 3}},
            {"approved_by": "manager", "reason": "理由", "fields": ["labor.unknowns"],
             "range": {"low": 3, "typical": 2, "high": 1}},
            {"approved_by": "manager", "reason": "理由", "fields": ["labor.unknowns"],
             "range": {"low": 1, "typical": float("nan"), "high": 3}},
            {"approved_by": "manager", "reason": "理由",
             "fields": ["labor.unknowns", "labor.unknowns"],
             "range": {"low": 1, "typical": 2, "high": 3}},
        ]
        for approval in cases:
            with self.subTest(approval=approval):
                inputs = demo_inputs()
                inputs["labor"]["unknowns"] = ["錆"]
                inputs["conditional_approval"] = approval
                result = question_guide(inputs)
                self.assertEqual(result["status"], "blocked")
                self.assertFalse(result["can_calculate"])
                self.assertEqual(result["questions"][0]["status"], "unanswered")


class AnswersToInputsTests(unittest.TestCase):
    def test_applies_explicit_dot_paths_on_copy_without_mutating_original(self):
        inputs = demo_inputs()
        before = deepcopy(inputs)

        updated = answers_to_inputs(inputs, {
            "labor.person_hours.typical": 2,
            "items.0.quantity_range.high": 4,
            "vehicle.color": "未確認",
        })

        self.assertEqual(updated["labor"]["person_hours"]["typical"], 2)
        self.assertEqual(updated["items"][0]["quantity_range"]["high"], 4)
        self.assertEqual(updated["vehicle"]["color"], "未確認")
        self.assertEqual(inputs, before)
        updated["items"][0]["quantity_range"]["high"] = 99
        self.assertEqual(inputs["items"][0]["quantity_range"]["high"], 1)

    def test_does_not_turn_unknown_into_zero_or_add_defaults(self):
        inputs = {"labor": {"unknowns": ["錆"]}}
        updated = answers_to_inputs(inputs, {"labor.unknowns": ["錆"]})
        self.assertEqual(updated, inputs)
        self.assertNotIn("person_hours", updated["labor"])
        self.assertNotIn("labor_rate", updated)

    def test_invalid_path_fails_without_mutating_original(self):
        inputs = {"items": []}
        before = deepcopy(inputs)
        with self.assertRaises(ValueError):
            answers_to_inputs(inputs, {"items.0.price": 10})
        self.assertEqual(inputs, before)


if __name__ == "__main__":
    unittest.main()
