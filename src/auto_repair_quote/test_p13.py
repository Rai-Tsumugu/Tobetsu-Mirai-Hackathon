from __future__ import annotations

import unittest
from copy import deepcopy

from .common import QuoteError
from .fixtures import demo_inputs
from .p13 import advance_step, form_state, validate_step


class QuoteStepperTests(unittest.TestCase):
    def setUp(self):
        self.inputs = demo_inputs()
        self.inputs.update(vehicle_ref="V-DEMO-01", job_ref="JOB-DEMO-01")
        self.quote = {
            "total": {"low": 100, "typical": 150, "high": 200},
            "selected_band": "typical",
            "confirmed_by": "operator-demo-01",
        }

    def test_vehicle_and_job_refs_are_required_anonymous_identifiers(self):
        self.assertEqual(validate_step({}, 0)[0]["code"], "missing_vehicle_ref")
        self.assertEqual(validate_step({"vehicle_ref": " "}, 0)[0]["code"], "missing_vehicle_ref")
        self.assertEqual(validate_step({}, 1)[0]["code"], "missing_job_ref")
        self.assertEqual(validate_step({"vehicle_ref": "V1"}, 0), [])
        self.assertEqual(validate_step({"job_ref": "J1"}, 1), [])

    def test_conditions_step_delegates_to_p03_validation(self):
        self.assertEqual(validate_step(self.inputs, 2), [])
        invalid = deepcopy(self.inputs)
        invalid["labor_rate"]["basis"][0]["unit"] = "円/式"
        self.assertTrue(any(issue["code"] == "invalid_rate_unit" for issue in validate_step(invalid, 2)))

    def test_amount_requires_a_finite_complete_proposed_range(self):
        self.assertEqual(validate_step(self.inputs, 3, self.quote), [])
        for total in (None, {"low": 1, "typical": 2}, {"low": 1, "typical": float("inf"), "high": 3}):
            self.assertEqual(validate_step(self.inputs, 3, {"total": total})[0]["code"], "invalid_proposed_amount")

    def test_confirmation_requires_selected_band_and_confirmer(self):
        self.assertEqual(validate_step(self.inputs, 4, self.quote), [])
        issues = validate_step(self.inputs, 4, {"selected_band": "outside", "confirmed_by": " "})
        self.assertEqual({issue["code"] for issue in issues}, {"missing_selected_band", "missing_confirmed_by", "invalid_proposed_amount"})
        self.assertTrue(validate_step(self.inputs, 4, {"selected_band":"typical", "confirmed_by":"demo"}))

    def test_advance_deepcopies_and_refuses_missing_and_unsupported_steps(self):
        draft = {"step": 0, "inputs": self.inputs, "validation_state": {"ok": True}, "updated_at": "now"}
        before = deepcopy(draft)
        next_draft = advance_step(draft)
        self.assertEqual(next_draft["step"], 1)
        self.assertEqual(draft, before)
        next_draft["inputs"]["labor"]["person_hours"]["low"] = 99
        self.assertEqual(draft["inputs"]["labor"]["person_hours"]["low"], 1)
        with self.assertRaises(QuoteError):
            advance_step({"step": 0, "inputs": {}})
        for invalid_step in (-1, 5, True, "0"):
            with self.assertRaises(QuoteError):
                validate_step(self.inputs, invalid_step)

    def test_form_state_reports_gate_and_step_label(self):
        state = form_state({}, step=0)
        self.assertEqual(state["label"], "vehicle")
        self.assertFalse(state["can_advance"])
        self.assertTrue(form_state(self.inputs, step=2)["can_advance"])


if __name__ == "__main__":
    unittest.main()
