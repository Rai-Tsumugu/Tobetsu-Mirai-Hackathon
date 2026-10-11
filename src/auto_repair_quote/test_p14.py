from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime

from .common import QuoteError
from .p14 import confirm_quote


class QuoteConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.quote = {
            "total": {"low": 100, "typical": 150, "high": 200},
            "status": "proposed",
            "reasons": ["calculation basis"],
            "conditions": ["subject to inspection"],
        }

    def test_confirms_explicitly_selected_band_and_preserves_snapshot(self):
        original = deepcopy(self.quote)
        confirmed = confirm_quote(self.quote, "typical", "operator-1")
        self.assertEqual(self.quote, original)
        self.assertEqual(confirmed["total"], original["total"])
        self.assertEqual(confirmed["reasons"], original["reasons"])
        self.assertEqual(confirmed["conditions"], original["conditions"])
        self.assertEqual(confirmed["confirmation"]["proposed_amount"], 150)
        self.assertEqual(confirmed["confirmation"]["final_amount"], 150)
        datetime.fromisoformat(confirmed["confirmation"]["confirmed_at"])
        confirmed["conditions"].append("changed")
        self.assertEqual(self.quote["conditions"], ["subject to inspection"])

    def test_manual_in_range_override_requires_reason(self):
        with self.assertRaises(QuoteError):
            confirm_quote(self.quote, "typical", "operator-1", 175)
        confirmed = confirm_quote(self.quote, "typical", "operator-1", 175, "manual adjustment")
        self.assertEqual(confirmed["confirmation"]["final_amount"], 175)
        self.assertEqual(confirmed["total"], self.quote["total"])
        self.assertEqual(confirmed["override_reason"], "manual adjustment")

    def test_out_of_range_override_requires_reason_and_valid_amount(self):
        with self.assertRaises(QuoteError):
            confirm_quote(self.quote, "high", "operator-1", 250)
        with self.assertRaises(QuoteError):
            confirm_quote(self.quote, "high", "operator-1", -1, "bad")
        with self.assertRaises(QuoteError):
            confirm_quote(self.quote, "high", "operator-1", float("inf"), "bad")
        confirmed = confirm_quote(self.quote, "high", "operator-1", 250, "customer-approved change")
        self.assertEqual(confirmed["confirmation"]["final_amount"], 250)

    def test_blocked_unknown_and_unresolved_quotes_are_rejected(self):
        for status in ("blocked", "unknown"):
            with self.subTest(status=status), self.assertRaises(QuoteError):
                confirm_quote({**self.quote, "status": status}, "low", "operator-1")
        with self.assertRaises(QuoteError):
            confirm_quote({**self.quote, "unknowns": ["labor amount"]}, "low", "operator-1")

    def test_null_or_invalid_range_missing_band_and_confirmer_are_rejected(self):
        for total in (None, {"low": 100, "typical": None, "high": 200},
                      {"low": 200, "typical": 150, "high": 100}):
            with self.subTest(total=total), self.assertRaises(QuoteError):
                confirm_quote({**self.quote, "total": total}, "low", "operator-1")
        for band in (None, "", "middle"):
            with self.subTest(band=band), self.assertRaises(QuoteError):
                confirm_quote(self.quote, band, "operator-1")
        with self.assertRaises(QuoteError):
            confirm_quote(self.quote, "low", " ")

    def test_confirmed_quote_cannot_be_changed_again(self):
        confirmed = confirm_quote(self.quote, "low", "operator-1")
        with self.assertRaises(QuoteError):
            confirm_quote(confirmed, "high", "operator-2")
        with self.assertRaises(QuoteError):
            confirm_quote({**self.quote, "status": "confirmed"}, "high", "operator-2")


if __name__ == "__main__":
    unittest.main()
