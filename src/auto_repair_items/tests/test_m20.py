"""M20 usage range proposal tests."""

import unittest

from auto_repair_items import m20
from auto_repair_items.core import DEMO_DATE, Store, ValidationError, demo_item


class M20Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def record_band(self, **changes):
        payload = {
            'action': 'record', 'item_id': 'paint-a', 'area_band': 'small',
            'low_qty': '1.2', 'typical_qty': '2.5', 'high_qty': '4', 'unit': 'ml',
            'evidence': '架空の工場記録に基づくテスト根拠', 'approved_by': '整備士A',
            'reason': '確認済みの目安',
        }
        payload.update(changes)
        return m20.run(payload, self.store)

    def test_defaults_are_a_fictional_save_action_and_do_not_create_price(self):
        result = m20.run(m20.SPEC['defaults'], self.store)

        self.assertEqual(result['status'], 'saved')
        self.assertTrue(result['simulator'])
        self.assertEqual(result['usage_band']['approved_by'], '架空デモ担当')
        self.assertEqual(self.store.price_versions(), [])

    def test_record_requires_ordered_quantities_evidence_and_approval(self):
        self.record_band()
        self.assertEqual(len(self.store.records(m20.NAMESPACE)), 1)
        for changes in (
            {'low_qty': '3', 'typical_qty': '2'},
            {'typical_qty': '5', 'high_qty': '4'},
            {'evidence': ' '},
            {'approved_by': ''},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.record_band(**changes)
        self.assertEqual(len(self.store.records(m20.NAMESPACE)), 1)

    def test_estimate_displays_decimal_quantity_and_same_unit_price_ranges(self):
        self.record_band()
        self.store.add_price(demo_item('paint-a', '販売', '10', 'ml'), '価格確認者')

        result = m20.run({'action': 'estimate', 'item_id': 'paint-a',
                          'area_band': 'small', 'as_of': DEMO_DATE}, self.store)

        self.assertEqual(result['status'], 'needs_human_confirmation')
        self.assertEqual(result['quantity']['low'], '1.2')
        self.assertEqual(result['quantity']['typical'], '2.5')
        self.assertEqual(result['candidate_amount'], {
            'low': '12.0', 'typical': '25.0', 'high': '40', 'currency': 'JPY',
        })
        self.assertEqual(result['unknowns'], [])
        self.assertEqual(len(self.store.price_versions('paint-a')), 1)

    def test_missing_or_unapproved_band_stops_with_null_quantity(self):
        self.store.add_price(demo_item('paint-a', '販売', '10', 'ml'), '価格確認者')
        missing = m20.run({'action': 'estimate', 'item_id': 'paint-a',
                           'area_band': 'small'}, self.store)
        self.store.put(m20.NAMESPACE, {
            'item_id': 'paint-a', 'area_band': 'small', 'low_qty': '1',
            'typical_qty': '2', 'high_qty': '3', 'unit': 'ml',
            'evidence': '架空根拠', 'approved_by': '', 'status': 'pending',
        }, record_id='paint-a:small')
        pending = m20.run({'action': 'estimate', 'item_id': 'paint-a',
                           'area_band': 'small'}, self.store)

        for result in (missing, pending):
            self.assertIsNone(result['quantity'])
            self.assertIsNone(result['candidate_amount'])
            self.assertTrue(result['unknowns'])

    def test_unregistered_price_and_unit_mismatch_stop_instead_of_zero(self):
        self.record_band()
        absent = m20.run({'action': 'estimate', 'item_id': 'paint-a',
                          'area_band': 'small'}, self.store)
        self.store.add_price(demo_item('paint-a', '販売', '10', 'L'), '価格確認者')
        mismatch = m20.run({'action': 'estimate', 'item_id': 'paint-a',
                            'area_band': 'small'}, self.store)

        for result in (absent, mismatch):
            self.assertIsNone(result['quantity'])
            self.assertIsNone(result['candidate_amount'])
            self.assertEqual(len(result['unknowns']), 1)

    def test_list_is_read_only_and_returns_only_latest_record_per_band(self):
        self.record_band()
        self.record_band(typical_qty='3', reason='改訂した架空目安')
        before = self.store.price_versions()

        result = m20.run({'action': 'list', 'item_id': 'paint-a'}, self.store)

        self.assertEqual(len(result['usage_bands']), 1)
        self.assertEqual(result['usage_bands'][0]['typical_qty'], '3')
        self.assertEqual(self.store.price_versions(), before)


if __name__ == '__main__':
    unittest.main()
