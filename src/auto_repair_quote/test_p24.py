"""Tests for P24 price history comparison."""

from copy import deepcopy
import unittest

from .common import QuoteError
from .p24 import compare_item_prices, price_comparison, save_price_history
from .store import QuoteStore


def record(**overrides):
    value = {
        "item_id": "SIM-PAINT-01",
        "price_type": "仕入",
        "unit": "缶",
        "unit_price": 100,
        "source": "simulator",
        "updated_at": "2026-10-11",
    }
    value.update(overrides)
    return value


class P24Tests(unittest.TestCase):
    def test_sales_price_is_not_marked_up_again(self):
        result = price_comparison([
            record(price_type="販売", unit_price=150, markup={"value": 9}),
        ], "SIM-PAINT-01")
        self.assertEqual(result["prices"][0]["selling_price_proposal"], {
            "low": 150, "typical": 150, "high": 150,
        })
        self.assertEqual(result["prices"][0]["confirmation_status"], "確認済み")

    def test_unapproved_purchase_markup_has_no_proposal(self):
        result = price_comparison([record(markup={"value": 1.5})], "SIM-PAINT-01")
        self.assertIsNone(result["prices"][0]["selling_price_proposal"])
        self.assertEqual(result["prices"][0]["confirmation_status"], "未確認")
        self.assertEqual(result["prices"][0]["unit_price"], 100)

    def test_different_units_stop_comparison(self):
        with self.assertRaises(ValueError):
            price_comparison([
                record(unit="缶"), record(unit="本", price_type="販売", unit_price=200),
            ], "SIM-PAINT-01")

    def test_store_round_trip_does_not_mutate_input_or_history(self):
        store = QuoteStore()
        original = record(markup={"value": 1.2})
        before = deepcopy(original)
        save_price_history(store, original)
        original["unit_price"] = 999
        result = compare_item_prices(store, "SIM-PAINT-01")
        self.assertEqual(before["unit_price"], 100)
        self.assertEqual(result["prices"][0]["unit_price"], 100)
        self.assertIsNone(result["prices"][0]["selling_price_proposal"])
        with self.assertRaises(QuoteError):
            save_price_history(store, record(unit_price=None))
        self.assertEqual(len(store.list_prices("SIM-PAINT-01")), 1)
        store.close()


if __name__ == "__main__":
    unittest.main()
