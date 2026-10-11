from __future__ import annotations

import unittest
from copy import deepcopy
from uuid import UUID

from .common import QuoteError
from .p18 import record_communication
from .store import QuoteStore


class CommunicationRecordTests(unittest.TestCase):
    def setUp(self):
        self.store = QuoteStore()
        self.quote = {
            "quote_id": "Q-18", "quote_version": 1, "status": "proposed",
            "total": {"low": 1000, "typical": 1200, "high": 1600},
            "customer_ref": "C-DEMO-01", "vehicle_ref": "V-DEMO-01",
        }
        self.store.save_quote(self.quote)
        self.data = {
            "selected_band": "typical", "customer_ref": "C-DEMO-01",
            "vehicle_ref": "V-DEMO-01", "operator": "operator-demo-01",
            "condition_note": "架空:現車確認後に再確定",
        }

    def tearDown(self):
        self.store.close()

    def test_uses_the_selected_amount_from_the_immutable_old_version(self):
        before_quote, before_data = deepcopy(self.quote), deepcopy(self.data)
        record = record_communication(self.store, self.quote, self.data)

        self.assertEqual(record["communicated_amount"], 1200)
        self.assertEqual(record["quote_version"], 1)
        self.assertEqual(self.store.get_quote("Q-18", 1), before_quote)
        self.assertEqual(self.quote, before_quote)
        self.assertEqual(self.data, before_data)

    def test_explicit_amount_wins_and_confirmed_final_amount_is_fallback(self):
        record = record_communication(self.store, self.quote, {**self.data, "communicated_amount": 1350})
        self.assertEqual(record["communicated_amount"], 1350)

        confirmed = {**self.quote, "quote_version": 2, "status": "confirmed", "selected_band":"typical", "confirmation": {"final_amount": 1299}}
        self.store.save_quote(confirmed)
        record = record_communication(self.store, confirmed, self.data)
        self.assertEqual(record["communicated_amount"], 1299)

    def test_missing_anonymous_references_are_rejected(self):
        for key in ("customer_ref", "vehicle_ref"):
            with self.subTest(key=key):
                missing = dict(self.data)
                missing.pop(key)
                with self.assertRaises(QuoteError):
                    record_communication(self.store, self.quote, missing)

    def test_personal_data_and_api_inputs_are_not_persisted(self):
        record = record_communication(self.store, self.quote, {
            **self.data, "customer_name": "架空 顧客", "phone": "09012345678",
            "audio": "recording", "inputs": {"private": "ignore"},
        })
        self.assertEqual(set(record), {
            "communication_id", "quote_id", "quote_version", "customer_ref",
            "vehicle_ref", "selected_band", "communicated_amount", "condition_note",
            "timestamp", "operator",
        })
        UUID(record["communication_id"])
        self.assertEqual(self.store.list_communications("Q-18"), [record])

    def test_unknown_or_blocked_amount_and_invalid_explicit_amount_are_rejected(self):
        unknown = {**self.quote, "quote_version": 2, "total": {"low": 1000, "typical": None, "high": 1600}}
        self.store.save_quote(unknown)
        with self.assertRaises(QuoteError):
            record_communication(self.store, unknown, self.data)
        blocked = {**self.quote, "quote_version": 3, "status": "blocked"}
        self.store.save_quote(blocked)
        with self.assertRaises(QuoteError):
            record_communication(self.store, blocked, self.data)
        for amount in (-1, float("inf"), True):
            with self.subTest(amount=amount), self.assertRaises(QuoteError):
                record_communication(self.store, self.quote, {**self.data, "communicated_amount": amount})

    def test_mismatched_unsaved_quote_is_rejected(self):
        edited = {**self.quote, "total": {"low": 1, "typical": 1, "high": 1}}
        with self.assertRaises(QuoteError):
            record_communication(self.store, edited, self.data)


if __name__ == "__main__":
    unittest.main()
