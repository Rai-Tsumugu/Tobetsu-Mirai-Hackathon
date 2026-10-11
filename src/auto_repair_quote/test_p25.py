from copy import deepcopy
import unittest

from .common import QuoteError
from .p25 import combine_quotes


def line(line_id, kind="parts", amount=100, item_id="I-1", usage_ref="use-1", **overrides):
    value = {
        "line_id": line_id, "kind": kind, "category": "部品" if kind == "parts" else "塗料",
        "description": line_id, "quantity_range": {"low": 1, "typical": 1, "high": 1},
        "unit": "個", "unit_price_range": amount, "amount": amount,
        "source_ref": item_id, "snapshot": {"item_id": item_id, "usage_ref": usage_ref},
    }
    value.update(overrides)
    return value


def quote(qid, lines, version=1):
    return {"quote_id": qid, "quote_version": version, "job_ref": f"job-{qid}", "lines": lines}


class CombineQuotesTests(unittest.TestCase):
    def setUp(self):
        self.quotes = [quote("Q1", [line("a")]), quote("Q2", [line("a", amount=120)])]

    def test_detects_shared_candidate_and_preserves_mismatch_details(self):
        result = combine_quotes(self.quotes)
        candidate = result["shared_item_candidates"][0]
        self.assertEqual(candidate["refs"], ["Q1:1:a", "Q2:1:a"])
        self.assertEqual(candidate["differences"][0]["differences"]["amount"]["candidate"], 120)
        self.assertEqual(result["subtotal"]["typical"], 220)
        self.assertEqual(result["accepted_dedup_refs"], [])

    def test_approved_explicit_ref_is_removed_and_original_subtotal_retained(self):
        result = combine_quotes(self.quotes, ["Q2:1:a"], "工場担当")
        self.assertEqual([row["line_ref"] for row in result["lines"]], ["Q1:1:a"])
        self.assertEqual(result["subtotal"]["typical"], 100)
        self.assertEqual(result["original_subtotal"]["typical"], 220)
        self.assertEqual(result["delta"]["typical"], -120)

    def test_rejects_unapproved_or_non_candidate_dedup_and_labor_removal(self):
        with self.assertRaises(QuoteError):
            combine_quotes(self.quotes, ["Q2:1:a"])
        with self.assertRaises(QuoteError):
            combine_quotes([quote("Q1", [line("labor", kind="labor")])], ["Q1:1:labor"], "担当")

    def test_separate_usage_refs_are_not_candidates(self):
        result = combine_quotes([quote("Q1", [line("a")]), quote("Q2", [line("b", usage_ref="use-2")])])
        self.assertEqual(result["shared_item_candidates"], [])
        self.assertEqual(result["subtotal"]["typical"], 200)

    def test_unknown_amount_band_stays_unknown_and_input_is_unchanged(self):
        quotes = [quote("Q1", [line("a", amount={"low": 10, "typical": None, "high": 30})])]
        original = deepcopy(quotes)
        result = combine_quotes(quotes)
        self.assertEqual(result["subtotal"], {"low": 10, "typical": None, "high": 30})
        self.assertEqual(quotes, original)

    def test_line_refs_are_namespaced(self):
        result = combine_quotes([quote("Q1", [line("same")]), quote("Q2", [line("same", item_id="I-2")])])
        self.assertEqual([row["line_id"] for row in result["lines"]], ["Q1:1:same", "Q2:1:same"])


if __name__ == "__main__":
    unittest.main()
