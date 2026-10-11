from __future__ import annotations

import unittest
from copy import deepcopy

from .p23 import compare_bands


class CompareBandsTests(unittest.TestCase):
    def setUp(self):
        self.quote = {
            "total": {"low": 100, "typical": 150, "high": 220},
            "lines": [
                {"line_id": "labor-1", "source_ref": "labor-source", "amount": {"low": 60, "typical": 90, "high": 130}},
                {"line_id": "part-1", "source_ref": "part-source", "amount": {"low": 40, "typical": 60, "high": 90}},
            ],
            "conditions": [
                {"condition_ref": "C-rust", "bands": ["high"], "text": "固着が確認された場合", "status": "approved"},
            ],
        }

    def test_compares_matching_band_lines_and_cites_applicable_conditions(self):
        result = compare_bands(self.quote)
        self.assertEqual([row["amount"] for row in result], [100, 150, 220])
        self.assertEqual(result[0]["condition_refs"], [])
        self.assertEqual(result[2]["condition_refs"], ["C-rust"])
        self.assertEqual(result[2]["conditions"][0]["text"], "固着が確認された場合")
        self.assertEqual(result[2]["line_ids"], ["labor-1", "part-1"])
        self.assertEqual(result[2]["contributions"][0]["difference_from_typical"], 40)
        self.assertEqual(result[2]["contributions"][0]["source_ref"], "labor-source")
        for band_row in result:
            self.assertEqual(sum(item["amount"] for item in band_row["contributions"]), band_row["amount"])
        self.assertEqual(result[0]["explanation_status"], "unexplained")
        self.assertEqual(result[2]["explanation_status"], "explained")

    def test_conditionless_difference_is_unexplained_without_invented_reason(self):
        quote = deepcopy(self.quote)
        quote["conditions"] = []
        row = compare_bands(quote)[2]
        self.assertEqual(row["explanation_status"], "unexplained")
        self.assertEqual(row["condition_refs"], [])
        self.assertEqual(row["conditions"], [])

    def test_null_band_values_remain_null(self):
        quote = {
            "total": {"low": 100, "typical": None, "high": 220},
            "lines": [{"line_id": "part", "source_ref": "catalog:item-1", "amount": {"low": 100, "typical": None, "high": 220}}],
            "conditions": [],
        }
        rows = compare_bands(quote)
        self.assertIsNone(rows[1]["amount"])
        self.assertIsNone(rows[1]["contributions"][0]["amount"])
        self.assertIsNone(rows[1]["contributions"][0]["difference_from_typical"])
        self.assertEqual(rows[1]["explanation_status"], "unexplained")
        self.assertEqual(rows[2]["contributions"][0]["source_ref"], "catalog:item-1")

    def test_does_not_mutate_quote_or_return_nested_aliases(self):
        original = deepcopy(self.quote)
        rows = compare_bands(self.quote)
        rows[2]["conditions"][0]["text"] = "changed"
        rows[2]["contributions"][0]["source_ref"] = "changed"
        self.assertEqual(self.quote, original)


if __name__ == "__main__":
    unittest.main()
