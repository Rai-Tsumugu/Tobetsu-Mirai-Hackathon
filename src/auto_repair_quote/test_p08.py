"""Focused tests for P08 width cards and explicit selection."""

import unittest
from copy import deepcopy

from .common import QuoteError
from .p08 import apply, band_cards


class P08Tests(unittest.TestCase):
    def test_builds_three_cards_and_only_selects_explicit_input(self):
        quote = {"total": {"low": 100, "typical": 150, "high": 220}, "conditions": []}
        result = apply(quote)
        self.assertEqual([card["amount"] for card in result["band_cards"]], [100, 150, 220])
        self.assertFalse(any(card["selected"] for card in result["band_cards"]))
        selected = apply(quote, {"selected_band": "high"})
        self.assertEqual(selected["selected_band"], "high")
        self.assertEqual([card["band"] for card in selected["band_cards"] if card["selected"]], ["high"])

    def test_applies_band_scoped_and_shared_conditions_with_refs(self):
        quote = {
            "total": {"low": 100, "typical": 150, "high": 220},
            "conditions": [
                {"condition_ref": "C-common", "text": "現車確認", "status": "open"},
                {"condition_ref": "C-high", "bands": ["high"], "text": "固着時", "status": "open"},
                {"condition_ref": "C-low", "band": "low", "text": "簡易作業", "status": "open"},
            ],
        }
        cards = band_cards(quote)
        self.assertEqual(cards[0]["condition_refs"], ["C-common", "C-low"])
        self.assertEqual(cards[1]["condition_refs"], ["C-common"])
        self.assertEqual(cards[2]["condition_refs"], ["C-common", "C-high"])

    def test_null_total_is_unconfirmed_and_never_coerced_to_zero(self):
        quote = {"total": {"low": 10, "typical": None, "high": 30}, "conditions": []}
        card = apply(quote)["band_cards"][1]
        self.assertIsNone(card["amount"])
        self.assertEqual(card["status"], "unconfirmed")
        self.assertEqual(card["label"], "未確認")
        self.assertFalse(card["selected"])
        with self.assertRaises(QuoteError):
            apply(quote, {"selected_band": "typical"})

    def test_blocked_quote_cannot_select_or_finalize_amount(self):
        quote = {"total": {"low": 10, "typical": 20, "high": 30}, "conditions": [], "status": "blocked"}
        cards = apply(quote)["band_cards"]
        self.assertTrue(all(card["status"] == "blocked" and card["label"] == "確定不可" for card in cards))
        self.assertFalse(any(card["selected"] for card in cards))
        with self.assertRaises(QuoteError):
            apply(quote, {"selected_band": "low"})

    def test_returns_copy_without_mutating_quote_or_nested_conditions(self):
        quote = {"total": {"low": 1, "typical": 2, "high": 3}, "conditions": [{"text": "確認", "meta": {"x": 1}}]}
        original = deepcopy(quote)
        result = apply(quote, {"selected_band": "low"})
        result["band_cards"][0]["conditions"][0]["meta"]["x"] = 9
        self.assertEqual(quote, original)
        self.assertNotIn("band_cards", quote)
        self.assertEqual(result["band_cards"][0]["conditions"][0]["meta"]["x"], 9)


if __name__ == "__main__":
    unittest.main()
