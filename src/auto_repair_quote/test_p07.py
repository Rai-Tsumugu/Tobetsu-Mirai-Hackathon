"""Focused tests for P07 quote category grouping and aggregation."""

import unittest
from copy import deepcopy

from .common import QuoteError
from .p07 import apply, group_lines


def line(line_id, kind, category, amount):
    return {"line_id": line_id, "kind": kind, "category": category, "amount": amount}


class P07Tests(unittest.TestCase):
    def test_separates_cost_categories_and_counts_scoped_adjustments_once(self):
        quote = {"lines": [
            line("labor-1", "labor", "labor", {"low": 100, "typical": 120, "high": 140}),
            line("part-1", "parts", "部品", 50),
            line("material-1", "materials", "塗料", {"low": 10, "typical": 20, "high": 30}),
            line("adj-labor", "adjustment", "labor", 5),
            line("adj-subtotal", "adjustment", "subtotal", 7),
        ]}
        result = apply(quote)
        self.assertEqual(result["labor_subtotal"], {"low": 100, "typical": 120, "high": 140})
        self.assertEqual(result["parts_subtotal"], {"low": 50, "typical": 50, "high": 50})
        self.assertEqual(result["materials_subtotal"], {"low": 10, "typical": 20, "high": 30})
        self.assertEqual(result["adjustments_subtotal"], {"low": 12, "typical": 12, "high": 12})
        self.assertEqual(result["subtotal"], {"low": 172, "typical": 202, "high": 232})
        self.assertNotIn("labor_subtotal", quote)

        groups = group_lines(quote)
        self.assertEqual(len(groups["adjustments"]["lines"]), 2)
        self.assertEqual(groups["adjustments"]["subtotal"], result["adjustments_subtotal"])

    def test_discount_accepts_reversed_negative_band_and_subtotal_nonnegative(self):
        quote = {"lines": [
            line("parts-1", "parts", "部品", {"low": 100, "typical": 200, "high": 300}),
            line("discount-1", "discount", None, {"low": -30, "typical": -20, "high": -10}),
        ]}
        result = apply(quote)
        self.assertEqual(result["adjustments_subtotal"], {"low": -30, "typical": -20, "high": -10})
        self.assertEqual(result["subtotal"], {"low": 70, "typical": 180, "high": 290})
        with self.assertRaises(QuoteError):
            apply({"lines": [line("discount-1", "discount", None, {"low": -120, "typical": -20, "high": -10})]})

    def test_positive_adjustment_can_have_reversed_bands(self):
        quote = {"lines": [
            line("labor-1", "labor", "labor", {"low": 0, "typical": 1000, "high": 2000}),
            line("parts-1", "parts", "部品", {"low": 0, "typical": 3000, "high": 4000}),
            line("floor", "adjustment", "labor", {"low": 2000, "typical": 0, "high": 0}),
        ]}
        self.assertEqual(apply(quote)["adjustments_subtotal"], {"low": 2000, "typical": 0, "high": 0})

    def test_missing_null_nan_amount_and_unknown_kind_stop(self):
        invalid = [
            line("x", "parts", "部品", None),
            {"line_id": "x", "kind": "parts", "category": "部品"},
            line("x", "parts", "部品", {"low": 1, "typical": float("nan"), "high": 3}),
            line("x", "mystery", "部品", 1),
        ]
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(QuoteError):
                apply({"lines": [row]})

    def test_duplicate_line_ids_and_category_mismatch_stop(self):
        row = line("same", "parts", "部品", 1)
        with self.assertRaises(QuoteError):
            apply({"lines": [row, deepcopy(row)]})
        with self.assertRaises(QuoteError):
            apply({"lines": [line("x", "parts", "塗料", 1)]})


if __name__ == "__main__":
    unittest.main()
