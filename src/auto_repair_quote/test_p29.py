from __future__ import annotations

import unittest
from uuid import UUID

from .common import QuoteError
from .p18 import record_communication
from .p29 import list_change_events, record_change
from .store import QuoteStore


class ChangeEventTests(unittest.TestCase):
    def setUp(self):
        self.store = QuoteStore()
        self.old = {
            "quote_id": "Q-29", "quote_version": 1, "status": "proposed",
            "customer_ref": "C-DEMO-01", "vehicle_ref": "V-DEMO-01",
            "lines": [{"line_id": "L1", "amount": {"low": 100, "typical": 120, "high": 150}}],
            "total": {"low": 100, "typical": 120, "high": 150}, "conditions": [{"condition_ref": "C1", "text": "旧条件"}],
        }
        self.new = {
            **self.old, "quote_version": 2,
            "lines": [self.old["lines"][0], {"line_id": "L2", "amount": {"low": 20, "typical": 30, "high": 40}}],
            "total": {"low": 120, "typical": 150, "high": 190}, "conditions": [{"condition_ref": "C1", "text": "追加作業の条件"}],
        }
        self.store.save_quote(self.old)
        self.store.save_quote(self.new)
        self.data = {
            "quote_id": "Q-29", "from_version": 1, "to_version": 2,
            "trigger_ref": "L2", "operator": "operator-demo-01",
            "condition_note": "架空:追加作業の条件を説明", "ack_status": "pending",
        }

    def tearDown(self):
        self.store.close()

    def _saved_communication(self, condition_note=None):
        quote = self.store.get_quote("Q-29", 2)
        return record_communication(self.store, quote, {
            "selected_band": "typical", "customer_ref": "C-DEMO-01",
            "vehicle_ref": "V-DEMO-01", "operator": "operator-demo-01",
            "condition_note": condition_note or self.data["condition_note"],
        })

    def test_pending_event_records_delta_and_does_not_claim_work_can_continue(self):
        event = record_change(self.store, self.data)
        UUID(event["event_id"])
        self.assertTrue(event["timestamp"].endswith("+00:00"))
        self.assertEqual(event["ack_status"], "pending")
        self.assertEqual(event["work_status"], "pending")
        self.assertEqual(event["delta_lines"]["added"][0]["line_id"], "L2")
        self.assertEqual(event["amount_delta"], {"low": 20, "typical": 30, "high": 40})
        self.assertEqual(list_change_events(self.store, "Q-29"), [event])

    def test_accepted_requires_matching_saved_communication(self):
        with self.assertRaises(QuoteError):
            record_change(self.store, {**self.data, "ack_status": "accepted"})
        communication = self._saved_communication()
        event = record_change(self.store, {
            **self.data, "ack_status": "accepted", "communication_id": communication["communication_id"],
        })
        self.assertEqual(event["communicated_amount"], 150)
        self.assertEqual(event["work_status"], "continue")

    def test_invalid_versions_and_cross_quote_versions_are_rejected(self):
        for override in ({"from_version": 3}, {"to_version": 1}, {"from_version": True}):
            with self.subTest(override=override), self.assertRaises(QuoteError):
                record_change(self.store, {**self.data, **override})
        other = {**self.new, "quote_id": "Q-OTHER"}
        self.store.save_quote(other)
        with self.assertRaises(QuoteError):
            record_change(self.store, {**self.data, "to_version": 2, "quote_id": "Q-OTHER"})

    def test_old_or_mismatched_communication_is_rejected(self):
        old_comm = record_communication(self.store, self.old, {
            "selected_band": "typical", "customer_ref": "C-DEMO-01",
            "vehicle_ref": "V-DEMO-01", "operator": "operator-demo-01",
            "condition_note": self.data["condition_note"],
        })
        with self.assertRaises(QuoteError):
            record_change(self.store, {**self.data, "ack_status": "accepted", "communication_id": old_comm["communication_id"]})
        mismatched = self._saved_communication("架空:異なる条件")
        with self.assertRaises(QuoteError):
            record_change(self.store, {**self.data, "ack_status": "accepted", "communication_id": mismatched["communication_id"]})

    def test_declined_event_blocks_work_and_extra_personal_data_is_not_saved(self):
        event = record_change(self.store, {**self.data, "ack_status": "declined", "customer_name": "secret", "phone": "09012345678", "audio": "secret"})
        self.assertEqual(event["work_status"], "blocked")
        self.assertNotIn("customer_name", event)
        self.assertNotIn("phone", event)
        self.assertNotIn("audio", event)
        count = len(self.store.list_change_events("Q-29"))
        with self.assertRaises(QuoteError):
            record_change(self.store, {**self.data, "ack_status": "accepted", "communication_id": "missing"})
        self.assertEqual(len(self.store.list_change_events("Q-29")), count)


if __name__ == "__main__":
    unittest.main()
