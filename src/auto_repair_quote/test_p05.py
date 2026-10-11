"""Focused tests for P05 approved discount behavior."""

import copy
import unittest

from .common import QuoteError
from .p05 import apply


def quote():
    return {
        "lines": [
            {"line_id": "labor:1", "kind": "labor", "category": "labor", "amount": {"low": 100, "typical": 200, "high": 300}},
            {"line_id": "parts:1", "kind": "parts", "category": "部品", "amount": {"low": 50, "typical": 100, "high": 150}},
        ],
        "subtotal": {"low": 150, "typical": 300, "high": 450},
        "tax": {"low": 10, "typical": 20, "high": 30},
        "total": {"low": 160, "typical": 320, "high": 480},
        "reasons": [],
    }


def discount(**overrides):
    value = {
        "scope": "lines",
        "line_ids": ["labor:1"],
        "kind": "rate",
        "value": 0.1,
        "reason": "架空: 来店特典",
        "approved_by": "架空: 責任者",
        "order": "before_tax",
    }
    value.update(overrides)
    return {"discount": value}


class P05Tests(unittest.TestCase):
    def test_applies_approved_line_rate_as_negative_adjustment(self):
        original = quote()
        result = apply(original, discount())
        row = result["lines"][-1]
        self.assertEqual(row["kind"], "discount")
        self.assertEqual(row["amount"], {"low": -10, "typical": -20, "high": -30})
        self.assertEqual(result["subtotal"], {"low": 140, "typical": 280, "high": 420})
        self.assertEqual(result["tax"], {"low": None, "typical": None, "high": None})
        self.assertEqual(result["total"], {"low": None, "typical": None, "high": None})
        self.assertIn("来店特典", row["reason"])
        self.assertEqual(original["lines"], quote()["lines"])

    def test_subtotal_amount_and_reapply_replace_row(self):
        inputs = discount(scope="subtotal", line_ids=[], kind="amount", value=25)
        first = apply(quote(), inputs)
        second = apply(first, inputs)
        discounts = [row for row in second["lines"] if row["kind"] == "discount"]
        self.assertEqual(len(discounts), 1)
        self.assertEqual(discounts[0]["amount"], {"low": -25, "typical": -25, "high": -25})
        self.assertEqual(second["subtotal"], {"low": 125, "typical": 275, "high": 425})

    def test_tax_policy_recalculates_tax_and_total_after_discount(self):
        original = {
            "lines": [{"line_id": "labor:one", "kind": "labor", "category": "labor",
                       "amount": {"low": 100, "typical": 100, "high": 100}}],
            "subtotal": {"low": 100, "typical": 100, "high": 100},
            "tax": {"low": 10, "typical": 10, "high": 10},
            "total": {"low": 110, "typical": 110, "high": 110},
        }
        inputs = discount(scope="subtotal", line_ids=[], kind="amount", value=10)
        inputs["tax_policy"] = {"rate": 0.1, "rounding": "half_up", "source": "simulator"}
        result = apply(original, inputs)
        self.assertEqual(result["subtotal"], {"low": 90, "typical": 90, "high": 90})
        self.assertEqual(result["tax"], {"low": 9, "typical": 9, "high": 9})
        self.assertEqual(result["total"], {"low": 99, "typical": 99, "high": 99})

    def test_reapply_with_tax_policy_does_not_compound_discount(self):
        inputs = discount(scope="subtotal", line_ids=[], kind="amount", value=25)
        inputs["tax_policy"] = {"rate": 0, "rounding": "half_up", "source": "simulator"}
        first = apply(quote(), inputs)
        second = apply(first, inputs)
        self.assertEqual(second["subtotal"], first["subtotal"])
        self.assertEqual(second["total"], first["total"])
        self.assertEqual(sum(line["kind"] == "discount" for line in second["lines"]), 1)

    def test_requires_approval_reason_and_supported_order(self):
        for overrides in (
            {"approved_by": ""}, {"reason": ""}, {"order": "after_tax"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(QuoteError):
                apply(quote(), discount(**overrides))

    def test_rejects_rate_over_one_and_discount_over_target(self):
        for inputs in (discount(value=1.01), discount(kind="amount", value=301)):
            with self.subTest(inputs=inputs), self.assertRaises(QuoteError):
                apply(quote(), inputs)

    def test_does_not_mutate_input_or_quote(self):
        original = quote()
        inputs = discount()
        saved_quote, saved_inputs = copy.deepcopy(original), copy.deepcopy(inputs)
        apply(original, inputs)
        self.assertEqual(original, saved_quote)
        self.assertEqual(inputs, saved_inputs)


if __name__ == "__main__":
    unittest.main()
