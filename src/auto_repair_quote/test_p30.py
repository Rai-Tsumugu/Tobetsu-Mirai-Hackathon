from __future__ import annotations

import unittest
from copy import deepcopy

from .common import QuoteError
from .p30 import document_payload


class DocumentPayloadTests(unittest.TestCase):
    def setUp(self):
        self.quote = {
            "quote_id": "Q-30", "quote_version": 2, "status": "confirmed",
            "selected_band": "typical", "confirmed_by": "operator-demo-01",
            "confirmed_at": "2026-10-11T00:00:00+00:00", "override_reason": None,
            "lines": [{"line_id": "L1", "amount": {"low": 100, "typical": 120, "high": 150},
                       "snapshot": {"price": {"value": 120}}}],
            "subtotal": {"low": 100, "typical": 120, "high": 150},
            "tax": {"low": 10, "typical": 12, "high": 15},
            "total": {"low": 110, "typical": 132, "high": 165},
            "reasons": [{"text": "根拠"}], "conditions": [{"text": "条件"}],
            "sources": [{"snapshot": {"id": "S1"}}], "final_amount": 132,
            "confirmation": {"selected_band": "typical", "confirmed_by": "operator-demo-01",
                "confirmed_at": "2026-10-11T00:00:00+00:00", "proposed_amount": 132,
                "final_amount": 132, "override_reason": None},
        }

    def test_proposed_payload_preserves_ranges_and_detaches_all_nested_data(self):
        original = deepcopy(self.quote)
        payload = document_payload(self.quote)
        self.assertEqual(payload["total"], original["total"])
        self.assertEqual(payload["selected_total"], 132)
        self.assertEqual(payload["final_amount"], 132)
        payload["lines"][0]["snapshot"]["price"]["value"] = 0
        payload["sources"][0]["snapshot"]["id"] = "changed"
        payload["conditions"][0]["text"] = "changed"
        self.assertEqual(self.quote, original)

    def test_override_is_explicit_and_does_not_recompute_tax_ranges(self):
        self.quote["final_amount"] = 140
        self.quote["override_reason"] = "架空:担当者調整"
        self.quote["confirmation"].update(final_amount=140, override_reason="架空:担当者調整")
        payload = document_payload(self.quote)
        self.assertEqual(payload["proposed_amount"], 132)
        self.assertEqual(payload["final_amount"], 140)
        self.assertEqual(payload["amount_adjustment"], 8)
        self.assertEqual(payload["tax"], self.quote["tax"])
        self.assertIn("未確認", payload["tax_allocation_note"])
        self.assertIn("請求書ではない", payload["tax_allocation_note"])

    def test_proposal_or_unknowns_are_rejected(self):
        for changes in ({"status": "proposed"}, {"unknowns": ["価格未確認"]}):
            with self.subTest(changes=changes), self.assertRaises(QuoteError):
                document_payload({**self.quote, **changes})

    def test_confirmation_identity_and_amount_conflicts_are_rejected(self):
        invalid = [
            {"confirmation": {**self.quote["confirmation"], "selected_band": "low"}},
            {"confirmation": {**self.quote["confirmation"], "confirmed_by": "another"}},
            {"confirmation": {**self.quote["confirmation"], "final_amount": 140}},
            {"final_amount": 140},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(QuoteError):
                document_payload({**self.quote, **changes})

    def test_subtotal_tax_total_ranges_must_match_without_recalculating(self):
        for band in ("low", "typical", "high"):
            with self.subTest(band=band):
                quote = deepcopy(self.quote)
                quote["subtotal"][band] += 1
                # Each range remains ordered, while this band no longer sums
                # to its recorded total.
                with self.assertRaisesRegex(
                    QuoteError, f"subtotal plus tax must match total for {band}"
                ):
                    document_payload(quote)

    def test_consistent_ranges_are_passed_through_unchanged(self):
        payload = document_payload(self.quote)
        self.assertEqual(payload["subtotal"], self.quote["subtotal"])
        self.assertEqual(payload["tax"], self.quote["tax"])
        self.assertEqual(payload["total"], self.quote["total"])

    def test_override_requires_reason_and_sources_are_snapshotted_from_lines(self):
        self.quote["final_amount"] = 140
        self.quote["confirmation"].update(final_amount=140, override_reason=None)
        self.quote["override_reason"] = None
        with self.assertRaises(QuoteError):
            document_payload(self.quote)
        self.quote["confirmation"]["override_reason"] = "架空:調整"
        self.quote["override_reason"] = "架空:調整"
        del self.quote["sources"]
        self.quote["lines"][0].update(source_system="catalog", source_ref="P-1")
        payload = document_payload(self.quote)
        payload["sources"][0]["snapshot"]["price"]["value"] = 0
        self.assertEqual(self.quote["lines"][0]["snapshot"]["price"]["value"], 120)


if __name__ == "__main__":
    unittest.main()
