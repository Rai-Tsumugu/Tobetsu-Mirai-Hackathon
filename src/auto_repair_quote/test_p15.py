from __future__ import annotations

import unittest
from copy import deepcopy
from sqlite3 import IntegrityError

from .common import QuoteError
from .p15 import revise_quote, save_version
from .store import QuoteStore


class QuoteRevisionTests(unittest.TestCase):
    def setUp(self):
        self.store = QuoteStore()
        self.original = {
            "quote_id": "Q-1",
            "quote_version": 1,
            "status": "confirmed",
            "selected_band": "typical",
            "confirmed_by": "operator-1",
            "confirmation": {"final_amount": 120},
            "override_reason": "approved",
            "metadata": {"input_snapshot": {"old": True}},
            "total": {"low": 100, "typical": 120, "high": 150},
        }
        self.store.save_quote(self.original)

    def tearDown(self):
        self.store.close()

    @staticmethod
    def calculate(inputs):
        price = inputs["price"]
        return {
            "quote_id": inputs["quote_id"],
            "quote_version": 1,
            "status": "confirmed",
            "selected_band": "high",
            "confirmed_by": "old operator",
            "confirmation": {"final_amount": 1},
            "override_reason": "old reason",
            "metadata": {"input_snapshot": {"stale": True}},
            "total": {"low": price, "typical": price, "high": price},
        }

    def test_revises_with_recalculated_inputs_without_changing_saved_version(self):
        source_before = deepcopy(self.store.get_quote("Q-1", 1))
        inputs = {"quote_id": "Q-1", "price": 250}
        inputs_before = deepcopy(inputs)

        revised = revise_quote(self.store, "Q-1", 1, inputs, self.calculate)

        self.assertEqual(revised["quote_version"], 2)
        self.assertEqual(revised["parent_version"], 1)
        self.assertEqual(revised["total"], {"low": 250, "typical": 250, "high": 250})
        self.assertEqual(revised["status"], "proposed")
        for field in ("selected_band", "confirmed_by", "confirmation", "override_reason"):
            self.assertIsNone(revised[field])
        self.assertEqual(revised["metadata"]["input_snapshot"]["price"], 250)
        self.assertEqual(inputs, inputs_before)
        self.assertEqual(self.store.get_quote("Q-1", 1), source_before)
        with self.assertRaises(ValueError):
            self.store.get_quote("Q-1", 2)

    def test_can_save_new_version_once_and_duplicate_is_rejected(self):
        revised = revise_quote(self.store, "Q-1", 1, {"price": 250}, self.calculate)
        saved = save_version(self.store, revised)
        self.assertEqual(self.store.get_quote("Q-1", 2), saved)
        with self.assertRaises(IntegrityError):
            save_version(self.store, revised)
        self.assertEqual(self.store.get_quote("Q-1", 1), self.original)

    def test_missing_source_and_mismatched_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            revise_quote(self.store, "Q-1", 2, {"price": 10}, self.calculate)
        with self.assertRaises(QuoteError):
            revise_quote(self.store, "Q-1", 1, {"quote_id": "Q-other", "price": 10}, self.calculate)

    def test_from_version_must_be_positive_integer_not_bool(self):
        for invalid in (0, -1, True, 1.0, "1"):
            with self.subTest(invalid=invalid), self.assertRaises(QuoteError):
                revise_quote(self.store, "Q-1", invalid, {"price": 10}, self.calculate)


if __name__ == "__main__":
    unittest.main()
