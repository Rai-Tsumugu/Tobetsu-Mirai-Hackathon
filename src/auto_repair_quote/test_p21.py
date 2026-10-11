from __future__ import annotations

import unittest
from copy import deepcopy

from .p21 import reoffer_quote, search_quotes
from .store import QuoteStore


class PreviousQuoteTests(unittest.TestCase):
    def setUp(self):
        self.store = QuoteStore()
        self.original = {
            "quote_id": "Q-1",
            "quote_version": 1,
            "customer_ref": "C-ANON-1",
            "vehicle_ref": "V-ANON-1",
            "job_ref": "J-BRAKE",
            "created_at": "2026-10-01T09:30:00+09:00",
            "status": "confirmed",
            "subtotal": {"low": 1000, "typical": 1200, "high": 1500},
            "total": {"low": 1100, "typical": 1320, "high": 1650},
            "metadata": {
                "input_snapshot": {
                    "labor": {"person_hours": {"low": 1, "typical": 1.2, "high": 1.5}},
                    "labor_rate": {"yen_per_person_hour": 1000, "effective_from": "2026-09-01"},
                    "items": [{"item_id": "PART-1", "unit_price": 200}],
                }
            },
        }
        self.store.save_quote(self.original)
        self.store.save_quote({**self.original, "quote_version": 2, "job_ref": "J-OTHER", "created_at": "2026-10-02T10:00:00+09:00"})
        self.store.save_quote({**self.original, "quote_id": "Q-2", "quote_version": 1, "customer_ref": "C-ANON-2"})

    def tearDown(self):
        self.store.close()

    def test_anonymous_exact_search_supports_combined_filters_and_preserves_snapshots(self):
        before = self.store.list_quotes()
        results = search_quotes(self.store, "C-ANON-1", "V-ANON-1", "J-BRAKE")

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["quote_id"], "Q-1")
        self.assertEqual(result["created_at"], "2026-10-01T09:30:00+09:00")
        self.assertEqual(result["total"], self.original["total"])
        self.assertEqual(result["metadata"]["input_snapshot"], self.original["metadata"]["input_snapshot"])
        self.assertTrue(result["reference_only"])
        self.assertIn("現在額として使用せず", result["history_notice"])

        result["metadata"]["input_snapshot"]["items"][0]["unit_price"] = 9999
        result["total"]["typical"] = 9999
        self.assertEqual(self.store.list_quotes(), before)

    def test_ref_search_returns_all_historical_versions(self):
        results = search_quotes(self.store, customer_ref="C-ANON-1")
        self.assertEqual({quote["quote_version"] for quote in results}, {1, 2})

    def test_reoffer_recalculates_current_inputs_without_saving(self):
        source_before = deepcopy(self.store.get_quote("Q-1", 1))
        seen_inputs = {}

        def calculate(inputs):
            seen_inputs.update(deepcopy(dict(inputs)))
            total = inputs["current_price"]
            return {
                "quote_id": inputs["quote_id"],
                "total": {"low": total, "typical": total, "high": total},
                "metadata": {"input_snapshot": {"stale": True}},
            }

        current_inputs = {"current_price": 2400, "checked_at": "2026-10-11"}
        inputs_before = deepcopy(current_inputs)
        proposed = reoffer_quote(self.store, "Q-1", 1, current_inputs, calculate)

        self.assertEqual(seen_inputs["current_price"], 2400)
        self.assertEqual(proposed["quote_version"], 3)
        self.assertEqual(proposed["parent_version"], 1)
        self.assertEqual(proposed["total"]["typical"], 2400)
        self.assertEqual(proposed["metadata"]["input_snapshot"]["checked_at"], "2026-10-11")
        self.assertEqual(current_inputs, inputs_before)
        self.assertEqual(self.store.get_quote("Q-1", 1), source_before)
        with self.assertRaises(ValueError):
            self.store.get_quote("Q-1", 3)


if __name__ == "__main__":
    unittest.main()
