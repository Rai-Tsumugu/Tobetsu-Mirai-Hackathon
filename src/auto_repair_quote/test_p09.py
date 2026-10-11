"""Focused tests for P09 band-specific tax calculation."""

import unittest
from copy import deepcopy

from .common import QuoteError
from .p09 import apply, tax_summary


def line(line_id, kind, category, amount):
    return {"line_id": line_id, "kind": kind, "category": category, "amount": amount}


def policy(**overrides):
    result = {"rate": "0.1", "rounding": "floor", "source": "simulator"}
    result.update(overrides)
    return {"tax_policy": result}


class P09Tests(unittest.TestCase):
    def test_discount_is_in_tax_base_and_total_matches_recalculated_subtotal(self):
        quote = {"lines": [
            line("part", "parts", "部品", {"low": 100, "typical": 200, "high": 300}),
            line("discount", "discount", None, {"low": -20, "typical": -30, "high": -50}),
        ]}
        original = deepcopy(quote)
        result = apply(quote, policy())
        self.assertEqual(result["subtotal"], {"low": 80, "typical": 170, "high": 250})
        self.assertEqual(result["tax"], {"low": 8, "typical": 17, "high": 25})
        self.assertEqual(result["total"], {"low": 88, "typical": 187, "high": 275})
        self.assertEqual(tax_summary(result)["typical"], {"subtotal": 170, "tax": 17, "total": 187})
        self.assertEqual(quote, original)

    def test_rounding_modes_are_applied_per_band(self):
        quote = {"lines": [line("p", "parts", "部品", {"low": 5, "typical": 15, "high": 25})]}
        self.assertEqual(apply(quote, policy(rounding="floor"))["tax"], {"low": 0, "typical": 1, "high": 2})
        self.assertEqual(apply(quote, policy(rounding="half_up"))["tax"], {"low": 1, "typical": 2, "high": 3})
        self.assertEqual(apply(quote, policy(rounding="ceil"))["tax"], {"low": 1, "typical": 2, "high": 3})

    def test_factory_requires_approval_and_unknown_taxable_id_stops(self):
        quote = {"lines": [line("p", "parts", "部品", 100)]}
        with self.assertRaises(QuoteError):
            apply(quote, policy(source="factory"))
        with self.assertRaises(QuoteError):
            apply(quote, policy(taxable_line_ids=["missing"]))
        with self.assertRaises(QuoteError):
            apply(quote, policy(source="factory", approved_by="operator-1", effective_date="2026-10-11"))
        result = apply(quote, policy(source="factory", approved_by="operator-1", effective_date="2026-10-11", taxable_line_ids=["p"]))
        self.assertEqual(result["tax_snapshot"]["approved_by"], "operator-1")

    def test_invalid_rates_and_unknown_settings_stop(self):
        quote = {"lines": [line("p", "parts", "部品", 100)]}
        for rate in (None, float("nan"), -0.1, 1.01):
            with self.subTest(rate=rate), self.assertRaises(QuoteError):
                apply(quote, policy(rate=rate))
        with self.assertRaises(QuoteError):
            apply(quote, policy(mystery=True))


if __name__ == "__main__":
    unittest.main()
