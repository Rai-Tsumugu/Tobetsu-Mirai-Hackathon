import copy
import unittest

from .common import QuoteError
from .p26 import compare_versions


def quote(version, lines=None, total=None, conditions=None, quote_id="Q-26"):
    return {
        "quote_id": quote_id,
        "quote_version": version,
        "lines": lines or [],
        "total": total or {"low": 100, "typical": 120, "high": 150},
        "conditions": conditions or [],
    }


class CompareVersionsTests(unittest.TestCase):
    def test_reports_added_removed_changed_line_and_condition_diffs(self):
        old_line = {"line_id": "L1", "source_ref": "labor:1", "reason": "旧根拠", "snapshot": {"hours": 1}, "amount": {"low": 10}}
        new_line = {"line_id": "L1", "source_ref": "labor:1", "reason": "更新根拠", "snapshot": {"hours": 2}, "amount": {"low": 20}}
        removed_line = {"line_id": "L2", "source_ref": "part:old", "reason": "旧品"}
        added_line = {"line_id": "L3", "source_ref": "part:new", "reason": "新品"}
        old = quote(1, [old_line, removed_line], conditions=[{"condition_ref": "rust", "value": "軽度"}, {"id": "noise"}])
        new = quote(2, [new_line, added_line], conditions=[{"condition_ref": "rust", "value": "重度"}, {"id": "paint"}])
        old_before = copy.deepcopy(old)
        result = compare_versions(old, new)
        self.assertEqual(result["added"], [added_line])
        self.assertEqual(result["removed"], [removed_line])
        self.assertEqual(result["changed"], [{"from": old_line, "to": new_line}])
        self.assertEqual(result["condition_delta"], {
            "added": [{"id": "paint"}], "removed": [{"id": "noise"}],
            "changed": [{"from": {"condition_ref": "rust", "value": "軽度"}, "to": {"condition_ref": "rust", "value": "重度"}}],
        })
        self.assertEqual(old, old_before)

    def test_matches_by_unique_source_ref_when_line_ids_change(self):
        old = quote(1, [{"line_id": "old", "source_ref": "part:1", "reason": "old"}])
        new = quote(2, [{"line_id": "new", "source_ref": "part:1", "reason": "new"}])
        result = compare_versions(old, new)
        self.assertEqual(len(result["changed"]), 1)
        self.assertEqual(result["added"], [])
        self.assertEqual(result["removed"], [])

    def test_ambiguous_source_ref_warns_and_does_not_guess(self):
        old = quote(1, [{"line_id": "a", "source_ref": "same"}, {"line_id": "b", "source_ref": "same"}])
        new = quote(2, [{"line_id": "c", "source_ref": "same"}])
        result = compare_versions(old, new)
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(len(result["removed"]), 2)
        self.assertEqual(len(result["warnings"]), 1)

    def test_amount_delta_uses_signed_decimal_band_differences_and_nulls(self):
        old = quote(1, total={"low": "0.1", "typical": 5, "high": 10})
        new = quote(2, total={"low": "0.3", "typical": None, "high": 8})
        self.assertEqual(compare_versions(old, new)["amount_delta"], {"low": 0.2, "typical": None, "high": -2})

    def test_rejects_different_quote(self):
        with self.assertRaises(QuoteError):
            compare_versions(quote(1), quote(2, quote_id="OTHER"))


if __name__ == "__main__":
    unittest.main()
