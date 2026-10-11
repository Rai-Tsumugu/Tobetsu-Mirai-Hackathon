from __future__ import annotations

import sqlite3
import unittest
from copy import deepcopy

from .common import QuoteError
from .fixtures import demo_inputs
from .p14 import confirm_quote
from .p27 import load_snapshot, save_snapshot
from .pipeline import calculate
from .store import QuoteStore


class QuoteSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.store = QuoteStore()
        inputs = demo_inputs()
        inputs.update(quote_id="Q-P27", quote_version=1)
        proposed = calculate(inputs)
        self.quote = confirm_quote(proposed, "typical", "operator-demo-01")

    def tearDown(self):
        self.store.close()

    def test_pipeline_quote_is_snapshotted_immutably_and_loaded_by_version(self):
        original = deepcopy(self.quote)
        saved = save_snapshot(self.store, self.quote)
        self.assertEqual(self.quote, original)
        self.assertEqual(saved["inputs"], original["metadata"]["input_snapshot"])
        self.assertEqual(saved["subtotals"]["subtotal"], original["subtotal"])
        self.assertEqual(load_snapshot(self.store, "Q-P27", 1), saved)
        self.assertEqual(load_snapshot(self.store, "Q-P27"), saved)

        saved["metadata"]["input_snapshot"]["items"].clear()
        loaded = load_snapshot(self.store, "Q-P27", 1)
        self.assertTrue(loaded["inputs"]["items"])
        loaded["lines"].clear()
        self.assertTrue(load_snapshot(self.store, "Q-P27", 1)["lines"])

    def test_manual_final_amount_is_stored_only_with_reason(self):
        inputs = demo_inputs()
        inputs.update(quote_id="Q-P27", quote_version=2)
        quote = confirm_quote(calculate(inputs), "typical", "operator-2", 12345, "approved change")
        # A reasoned final amount may intentionally differ from the chosen band.
        saved = save_snapshot(self.store, quote)
        self.assertEqual(saved["final_amount"], 12345)
        self.assertEqual(load_snapshot(self.store, "Q-P27", 2)["override_reason"], "approved change")

    def test_pipeline_discount_and_unordered_minimum_adjustment_are_persistable(self):
        discount_inputs = demo_inputs()
        discount_inputs.update(
            quote_id="Q-P27-DISCOUNT", quote_version=1,
            discount={
                "order": "before_tax", "scope": "subtotal", "kind": "rate",
                "value": 0.1, "line_ids": [], "approved_by": "operator-1",
                "reason": "approved simulator discount",
            },
        )
        discount_quote = calculate(discount_inputs)
        self.assertEqual(discount_quote["status"], "proposed")
        discount_line = next(line for line in discount_quote["lines"] if line["kind"] == "discount")
        self.assertLess(discount_line["amount"]["typical"], 0)
        discount_confirmed = confirm_quote(discount_quote, "typical", "operator-1")
        discount_saved = save_snapshot(self.store, discount_confirmed)
        self.assertEqual(load_snapshot(self.store, "Q-P27-DISCOUNT", 1), discount_saved)

        minimum_inputs = demo_inputs()
        minimum_inputs.update(
            quote_id="Q-P27-MINIMUM", quote_version=1,
            minimum_rule={
                "scope": "subtotal", "amount": 50000, "effective_from": "2026-10-01",
                "approved_by": "operator-1", "reason": "simulator floor",
            },
        )
        minimum_quote = calculate(minimum_inputs)
        self.assertEqual(minimum_quote["status"], "proposed")
        adjustment = next(line for line in minimum_quote["lines"] if line["kind"] == "adjustment")
        self.assertGreater(adjustment["amount"]["low"], adjustment["amount"]["high"])
        minimum_confirmed = confirm_quote(minimum_quote, "typical", "operator-1")
        minimum_saved = save_snapshot(self.store, minimum_confirmed)
        self.assertEqual(load_snapshot(self.store, "Q-P27-MINIMUM", 1), minimum_saved)

    def test_rejects_incomplete_confirmation_inputs_sources_and_invalid_ranges(self):
        cases = []
        cases.append(self.quote | {"status": "proposed"})
        cases.append(self.quote | {"selected_band": "middle"})
        cases.append(self.quote | {"confirmed_by": " "})
        mismatched_band = deepcopy(self.quote)
        mismatched_band["confirmation"]["selected_band"] = "high"
        cases.append(mismatched_band)
        mismatched_amount = deepcopy(self.quote)
        mismatched_amount["confirmation"]["final_amount"] += 1
        cases.append(mismatched_amount)
        missing_confirmation = deepcopy(self.quote)
        missing_confirmation.pop("confirmation")
        cases.append(missing_confirmation)
        no_date = deepcopy(self.quote)
        no_date.pop("confirmed_at")
        no_date["confirmation"].pop("confirmed_at")
        cases.append(no_date)
        no_inputs = deepcopy(self.quote)
        no_inputs["metadata"]["input_snapshot"].pop("items")
        cases.append(no_inputs)
        nonfinite_input = deepcopy(self.quote)
        nonfinite_input["metadata"]["input_snapshot"]["labor_rate"]["yen_per_person_hour"] = float("inf")
        cases.append(nonfinite_input)
        no_source = deepcopy(self.quote)
        no_source["lines"][0]["snapshot"] = {}
        cases.append(no_source)
        nonfinite = deepcopy(self.quote)
        nonfinite["subtotal"]["typical"] = float("nan")
        cases.append(nonfinite)
        unbalanced = deepcopy(self.quote)
        unbalanced["total"]["low"] += 1
        cases.append(unbalanced)
        unreasoned_override = deepcopy(self.quote)
        unreasoned_override["final_amount"] = 999999
        unreasoned_override["override_reason"] = None
        unreasoned_override["confirmation"]["final_amount"] = 999999
        cases.append(unreasoned_override)
        for quote in cases:
            with self.subTest(quote=quote), self.assertRaises(QuoteError):
                save_snapshot(self.store, quote)

    def test_version_is_immutable_and_unknown_version_is_not_created(self):
        save_snapshot(self.store, self.quote)
        changed = deepcopy(self.quote)
        changed["reasons"].append("different snapshot")
        with self.assertRaises(sqlite3.IntegrityError):
            save_snapshot(self.store, changed)
        with self.assertRaises(ValueError):
            load_snapshot(self.store, "Q-P27", 2)

    def test_rejects_invalid_version_type(self):
        for version in (0, -1, True, 1.0, "1"):
            quote = deepcopy(self.quote)
            quote["quote_version"] = version
            with self.subTest(version=version), self.assertRaises(QuoteError):
                save_snapshot(self.store, quote)


if __name__ == "__main__":
    unittest.main()
