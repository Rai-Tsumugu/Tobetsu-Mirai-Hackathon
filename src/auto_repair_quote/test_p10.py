"""Focused tests for P10 provenance badges."""

import unittest
from copy import deepcopy

from .p10 import apply, source_badges


class P10Tests(unittest.TestCase):
    def test_simulator_item_is_labeled_fictional(self):
        quote = {"lines": [{
            "line_id": "item-price:SIM-1", "kind": "parts", "amount": {"low": 10, "typical": 10, "high": 10},
            "source_system": "simulator", "source_ref": "SIM-1",
            "snapshot": {"item_id": "SIM-1", "price_type": "販売", "source": "simulator", "updated_at": "2026-10-11"},
        }]}
        badge = source_badges(quote)[0]
        self.assertTrue(badge["fictional"])
        self.assertEqual(badge["status"], "fictional")
        self.assertIn("架空", badge["label"])

    def test_missing_source_is_unconfirmed(self):
        quote = {"lines": [{"line_id": "x", "kind": "parts", "snapshot": {"price_type": "販売"}}]}
        badge = source_badges(quote)[0]
        self.assertEqual(badge["status"], "unconfirmed")
        self.assertIn("未確認", badge["label"])
        self.assertFalse(badge["fictional"])

    def test_contract_source_does_not_claim_terms_were_checked(self):
        quote = {"lines": [{
            "line_id": "x", "kind": "parts", "source_system": "external_contract",
            "source_ref": "supplier-1", "snapshot": {"source": "contract", "updated_at": "2026-10-11", "price_type": "仕入"},
        }]}
        badge = source_badges(quote)[0]
        self.assertEqual(badge["status"], "contract_unconfirmed")
        self.assertEqual(badge["label"], "契約条件未確認")

    def test_labor_uses_rate_effective_date_and_basis(self):
        quote = {"lines": [{
            "line_id": "labor-total", "kind": "labor", "source_system": "labor_engine", "source_ref": "labor-1",
            "snapshot": {"labor_rate": {"effective_from": "2026-10-01", "basis": [{"label": "架空: 工場設定", "value": 8000, "unit": "円/人時"}]}},
        }]}
        badge = source_badges(quote)[0]
        self.assertEqual(badge["updated_at"], "2026-10-01")
        self.assertEqual(badge["price_type"], "工賃")
        self.assertTrue(badge["fictional"])
        self.assertEqual(badge["status"], "fictional")

    def test_apply_preserves_quote_and_all_amounts(self):
        quote = {"subtotal": {"low": 12, "typical": 15, "high": 19}, "total": {"low": 13, "typical": 16, "high": 20}, "lines": [
            {"line_id": "x", "kind": "parts", "amount": {"low": 12, "typical": 15, "high": 19}, "snapshot": {}}
        ]}
        original = deepcopy(quote)
        result = apply(quote)
        result["source_badges"][0]["label"] = "changed"
        self.assertEqual(quote, original)
        self.assertEqual(result["subtotal"], original["subtotal"])
        self.assertEqual(result["total"], original["total"])
        self.assertNotIn("source_badges", quote)


if __name__ == "__main__":
    unittest.main()
