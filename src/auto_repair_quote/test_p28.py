from __future__ import annotations

import unittest
from copy import deepcopy

from .common import QuoteError
from .p28 import append_communication, communication_ledger, query_communications
from .store import QuoteStore


class CommunicationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.store = QuoteStore()
        self.quote_v1 = {
            "quote_id": "Q-28", "quote_version": 1, "status": "proposed",
            "total": {"low": 1000, "typical": 1200, "high": 1600},
        }
        self.store.save_quote(self.quote_v1)
        self.data = {
            "selected_band": "typical", "customer_ref": "C-DEMO-01",
            "vehicle_ref": "V-DEMO-01", "operator": "operator-demo-01",
            "condition_note": "架空:現車確認後に再確定",
        }

    def tearDown(self):
        self.store.close()

    def test_appends_actual_communicated_amount_and_keeps_prior_versions_immutable(self):
        quote_before, data_before = deepcopy(self.quote_v1), deepcopy(self.data)
        first = append_communication(self.store, self.quote_v1, {
            **self.data, "communicated_amount": 1350,
        })
        quote_v2 = {**self.quote_v1, "quote_version": 2,
                    "total": {"low": 2000, "typical": 2500, "high": 3000}}
        self.store.save_quote(quote_v2)
        second = append_communication(self.store, quote_v2, {
            **self.data, "selected_band": "high", "communicated_amount": 2890,
        })

        self.assertEqual(first["communicated_amount"], 1350)
        self.assertEqual(second["communicated_amount"], 2890)
        self.assertEqual([r["quote_version"] for r in communication_ledger(self.store, "Q-28")], [1, 2])
        self.assertEqual(query_communications(self.store, "Q-28", quote_version=1), [first])
        self.assertEqual(query_communications(self.store, "Q-28", customer_ref="C-DEMO-01",
                                               vehicle_ref="V-DEMO-01"), [first, second])
        self.assertEqual(self.store.get_quote("Q-28", 1), quote_before)
        self.assertEqual(self.quote_v1, quote_before)
        self.assertEqual(self.data, data_before)

    def test_uses_selected_band_value_when_actual_amount_is_not_supplied(self):
        record = append_communication(self.store, self.quote_v1, self.data)
        self.assertEqual(record["communicated_amount"], 1200)

    def test_rejects_invalid_filter_and_does_not_rewrite_records(self):
        row = append_communication(self.store, self.quote_v1, {
            **self.data, "communicated_amount": 1111,
        })
        with self.assertRaises(QuoteError):
            query_communications(self.store, "Q-28", quote_version=True)
        self.assertEqual(self.store.list_communications("Q-28"), [row])


if __name__ == "__main__":
    unittest.main()
