from __future__ import annotations

import unittest
from copy import deepcopy

from .p12 import apply, customer_summary


class CustomerSummaryTests(unittest.TestCase):
    def setUp(self):
        self.quote = {
            "quote_version": 3,
            "status": "proposed",
            "selected_band": None,
            "total": {"low": 10000, "typical": 15000, "high": 24000},
            "lines": [
                {"kind": "labor", "amount": {"low": 8000, "typical": 12000, "high": 20000}},
                {"kind": "materials", "amount": {"low": 2000, "typical": 3000, "high": 4000}},
            ],
        }

    def test_no_band_explains_range_and_does_not_auto_select_typical(self):
        summary = customer_summary(self.quote)
        self.assertIsNone(summary["selected_band"])
        self.assertEqual(summary["amount"], self.quote["total"])
        self.assertIn("10,000〜24,000", summary["text"])
        self.assertIn("条件確認後に確定", summary["condition_note"])
        self.assertIn("工賃 8,000〜20,000 円", summary["text"])
        self.assertNotIn("工賃 12,000 円", summary["text"])

    def test_unknown_condition_requires_confirmation(self):
        quote = deepcopy(self.quote)
        quote["conditions"] = [{"text": "固着の有無", "status": "unknown"}]
        summary = customer_summary(quote, "typical")
        self.assertIsNone(summary["amount"])
        self.assertIn("確認後に確定します", summary["condition_note"])
        self.assertNotIn("15,000 円", summary["text"])

    def test_unknown_quote_status_blocks_amount_even_without_condition_rows(self):
        quote = deepcopy(self.quote)
        quote["status"] = "unknown"
        summary = customer_summary(quote, "typical")
        self.assertIsNone(summary["amount"])
        self.assertNotIn("15,000 円", summary["text"])

    def test_selected_band_shows_matching_component_amount(self):
        summary = customer_summary(self.quote, "typical")
        self.assertIn("工賃 12,000 円", summary["text"])

    def test_confirmed_final_amount_overrides_proposal_band(self):
        quote = deepcopy(self.quote)
        quote["confirmation"] = {"selected_band": "low", "final_amount": 17500, "confirmed_by": "operator-demo"}
        summary = customer_summary(quote, "low")
        self.assertEqual(summary["amount"], 17500)
        self.assertIn("確定額は 17,500 円", summary["text"])
        self.assertNotIn("low帯", summary["text"])

    def test_blocked_or_null_amount_is_never_presented_as_zero(self):
        quote = deepcopy(self.quote)
        quote["status"] = "blocked"
        quote["total"] = None
        summary = customer_summary(quote)
        self.assertIsNone(summary["amount"])
        self.assertIn("確認後に確定します", summary["text"])
        self.assertNotIn("0 円", summary["text"])

    def test_apply_is_non_destructive_and_marks_simulator_as_fictional(self):
        quote = deepcopy(self.quote)
        quote["lines"][0]["source_system"] = "simulator"
        original = deepcopy(quote)
        updated = apply(quote)
        self.assertTrue(updated["summary_snapshot"]["fictional"])
        self.assertIn("架空のSimulator", updated["summary_snapshot"]["text"])
        self.assertEqual(quote, original)
        updated["summary_snapshot"]["amount"]["low"] = -1
        self.assertEqual(quote, original)


if __name__ == "__main__":
    unittest.main()
