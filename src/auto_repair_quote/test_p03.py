import unittest
from copy import deepcopy

from .fixtures import demo_inputs
from .p03 import apply, validate_inputs


class P03Tests(unittest.TestCase):
    def setUp(self):
        self.inputs = demo_inputs()
        self.inputs["items"][0]["quantity_unit"] = " 個 "
        self.quote = {
            "status": "proposed",
            "lines": [{"kind": "item", "source_ref": "SIM-PART-001", "amount": {"low": 1000, "typical": 1000, "high": 1000}}],
            "subtotal": {"low": 1000, "typical": 1000, "high": 1000},
            "tax": {"low": 100, "typical": 100, "high": 100},
            "total": {"low": 1100, "typical": 1100, "high": 1100},
        }

    def test_valid_matching_units_remain_proposed(self):
        result = apply(self.quote, self.inputs)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["issues"], [])
        self.assertEqual(self.quote["status"], "proposed")
        self.assertEqual(self.quote["total"]["typical"], 1100)

    def test_unit_mismatch_blocks_and_nulls_affected_amount_and_total(self):
        self.inputs["items"][0]["quantity_unit"] = "缶"
        result = apply(self.quote, self.inputs)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["lines"][0]["amount"], None)
        self.assertIsNone(result["total"])
        self.assertTrue(any(issue["code"] == "unit_mismatch" for issue in result["issues"]))

    def test_unknowns_block_quote(self):
        self.inputs["labor"]["unknowns"] = ["架空: 未確認"]
        result = apply(self.quote, self.inputs)
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["total"])
        self.assertIn("unresolved_unknowns", [issue["code"] for issue in validate_inputs(self.inputs)])

    def test_invalid_quantity_ranges_block_quote(self):
        cases = [
            {"low": None, "typical": 1, "high": 1},
            {"low": float("inf"), "typical": 1, "high": 2},
            {"low": -1, "typical": 1, "high": 2},
            {"low": 2, "typical": 1, "high": 3},
        ]
        for quantity_range in cases:
            with self.subTest(quantity_range=quantity_range):
                self.inputs["items"][0]["quantity_range"] = quantity_range
                result = apply(self.quote, self.inputs)
                self.assertEqual(result["status"], "blocked")
                self.assertIsNone(result["lines"][0]["amount"])
                self.assertIsNone(result["total"])
                self.assertTrue(any(issue["code"] == "invalid_quantity_range" for issue in result["issues"]))

    def test_unit_checks_are_saved(self):
        result = apply(self.quote, self.inputs)
        self.assertEqual(len(result["unit_checks"]), 2)
        self.assertTrue(all(check["status"] == "matched" for check in result["unit_checks"]))
        self.assertEqual(result["unit_checks"][1]["source_ref"], "SIM-PART-001")

    def test_negative_person_hours_block_quote(self):
        self.inputs["labor"]["person_hours"]["low"] = -1
        result = apply(self.quote, self.inputs)
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["total"])
        self.assertTrue(any(issue["path"] == "labor.person_hours.low" for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
