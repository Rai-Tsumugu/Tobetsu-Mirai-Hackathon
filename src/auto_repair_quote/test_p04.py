"""Focused tests for P04 price validation and snapshot behavior."""

import unittest

from .common import QuoteError
from .p04 import apply, selling_price


def item(**overrides):
    value = {
        "item_id": "SIM-PAINT-01",
        "name": "架空: 塗料",
        "category": "塗料",
        "unit": "缶",
        "unit_price": {"low": 100, "typical": 120, "high": 150},
        "price_type": "仕入",
        "markup": {"value": 1.2, "approved_by": "架空: 社長", "reason": "架空: 掛率設定"},
        "source": "simulator",
        "updated_at": "2026-10-11",
        "quantity_range": {"low": 1, "typical": 2, "high": 3},
        "quantity_unit": "缶",
    }
    value.update(overrides)
    return value


class P04Tests(unittest.TestCase):
    def test_purchase_price_applies_multiplier_once_by_band(self):
        row = item()
        price = selling_price(row)
        self.assertEqual(price, {"low": 120, "typical": 144, "high": 180})

        quote = {"lines": []}
        result = apply(quote, {"items": [row]})
        line = result["lines"][0]
        self.assertEqual(line["kind"], "materials")
        self.assertEqual(line["unit_price_range"], price)
        self.assertEqual(line["amount"], {"low": 120, "typical": 288, "high": 540})
        self.assertEqual(line["snapshot"]["base_price"], row["unit_price"])
        self.assertEqual(line["snapshot"]["final_unit_price"], price)
        self.assertEqual(line["snapshot"]["markup"], row["markup"])
        reapplied = apply(result, {"items": [row]})
        self.assertEqual(reapplied["lines"], result["lines"])

    def test_sale_price_does_not_apply_markup(self):
        row = item(price_type="販売", unit_price=250, markup={"value": 9})
        self.assertEqual(selling_price(row), {"low": 250, "typical": 250, "high": 250})
        line = apply({"lines": []}, {"items": [row]})["lines"][0]
        self.assertIsNone(line["snapshot"]["markup"])
        self.assertEqual(line["amount"], {"low": 250, "typical": 500, "high": 750})

    def test_reapply_replaces_same_item_line_and_preserves_other_rows(self):
        original = {"lines": [
            {"line_id": "item-price:SIM-PAINT-01", "source_ref": "SIM-PAINT-01", "amount": {"typical": 1}},
            {"line_id": "other", "source_ref": "OTHER", "amount": 7},
        ]}
        result = apply(original, {"items": [item()]})
        self.assertEqual(len(result["lines"]), 2)
        self.assertEqual(result["lines"][1]["line_id"], "item-price:SIM-PAINT-01")
        self.assertEqual(original["lines"][0]["amount"], {"typical": 1})

    def test_unapproved_purchase_markup_stops(self):
        for invalid_markup in (
            None,
            {"value": 1.2, "reason": "理由のみ"},
            {"value": 1.2, "approved_by": "担当のみ"},
            {"value": None, "approved_by": "担当", "reason": "理由"},
        ):
            with self.subTest(markup=invalid_markup):
                with self.assertRaises(QuoteError):
                    selling_price(item(markup=invalid_markup))

    def test_null_price_and_unit_mismatch_stop(self):
        with self.assertRaises(QuoteError):
            apply({"lines": []}, {"items": [item(unit_price=None)]})
        with self.assertRaises(QuoteError):
            apply({"lines": []}, {"items": [item(quantity_unit="本")]})


if __name__ == "__main__":
    unittest.main()
