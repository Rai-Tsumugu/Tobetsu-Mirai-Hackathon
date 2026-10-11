"""Focused tests for P06 minimum amounts and safe reapplication."""

import unittest
from copy import deepcopy

from .common import QuoteError
from .p06 import apply


def rule(**overrides):
    value = {
        "scope": "labor",
        "amount": 10000,
        "effective_from": "2026-10-01",
        "approved_by": "架空: 社長",
        "reason": "架空: 最低工賃設定",
    }
    value.update(overrides)
    return value


def line(line_id, kind, amount):
    return {"line_id": line_id, "kind": kind, "amount": amount}


class P06Tests(unittest.TestCase):
    def test_labor_floor_adds_only_gap_by_band_and_preserves_input(self):
        original = {"lines": [
            line("labor", "labor", {"low": 4000, "typical": 12000, "high": 14000}),
            line("materials", "materials", {"low": 9000, "typical": 9000, "high": 9000}),
        ]}
        before = deepcopy(original)
        result = apply(original, {"minimum_rule": rule()})
        self.assertEqual(result["lines"][-1]["amount"], {"low": 6000, "typical": 0, "high": 0})
        self.assertEqual(result["lines"][-1]["category"], "labor")
        self.assertEqual(result["lines"][-1]["status"], "calculated")
        self.assertEqual(original, before)

    def test_subtotal_floor_includes_negative_discount_and_excludes_old_p06_row(self):
        quote = {"lines": [
            line("labor", "labor", {"low": 8000, "typical": 8000, "high": 12000}),
            line("discount", "discount", {"low": -1000, "typical": -1000, "high": -1000}),
            line("expense", "materials", {"low": 5000, "typical": 5000, "high": 5000}),
            line("minimum-rule-adjustment", "adjustment", {"low": 9000, "typical": 9000, "high": 9000}),
        ]}
        result = apply(quote, {"minimum_rule": rule(scope="subtotal", amount=15000)})
        self.assertEqual(result["lines"][-1]["amount"], {"low": 3000, "typical": 3000, "high": 0})
        twice = apply(result, {"minimum_rule": rule(scope="subtotal", amount=15000)})
        self.assertEqual(twice["lines"][-1]["amount"], result["lines"][-1]["amount"])
        self.assertEqual(sum(row["line_id"] == "minimum-rule-adjustment" for row in twice["lines"]), 1)

    def test_unapproved_rule_adds_proposed_warning_without_charging(self):
        result = apply({"lines": [line("labor", "labor", 100)]},
                       {"minimum_rule": rule(approved_by=None)})
        adjustment = result["lines"][-1]
        self.assertEqual(adjustment["amount"], {"low": 0, "typical": 0, "high": 0})
        self.assertEqual(adjustment["status"], "proposed")
        self.assertTrue(any("未承認" in reason for reason in result["reasons"]))

    def test_unconfigured_rule_is_noop_and_result_is_a_deep_copy(self):
        quote = {"lines": [{"amount": {"low": 1}}], "metadata": {"nested": [1]}}
        result = apply(quote, {})
        self.assertEqual(result, quote)
        self.assertIsNot(result, quote)
        self.assertIsNot(result["metadata"], quote["metadata"])

    def test_invalid_rule_and_invalid_non_discount_amounts_are_rejected(self):
        for bad_rule in (
            rule(scope="expenses"), rule(amount=-1), rule(amount=float("nan")),
            rule(effective_from="yesterday"), rule(reason=" "),
        ):
            with self.subTest(rule=bad_rule), self.assertRaises(QuoteError):
                apply({"lines": []}, {"minimum_rule": bad_rule})
        with self.assertRaises(QuoteError):
            apply({"lines": [line("parts", "parts", -1)]}, {"minimum_rule": rule()})


if __name__ == "__main__":
    unittest.main()
