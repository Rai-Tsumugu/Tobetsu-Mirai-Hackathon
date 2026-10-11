"""M24 condition-matched price timeline tests."""

import unittest

from auto_repair_items import m24
from auto_repair_items.core import Store, ValidationError, demo_item, seed_demo


class M24Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_default_reads_existing_demo_price_without_implicit_seed(self):
        empty = m24.run(m24.SPEC['defaults'], self.store)
        self.assertEqual(empty['versions'], [])
        self.assertEqual(self.store.price_versions(), [])
        seed_demo(self.store)
        result = m24.run(m24.SPEC['defaults'], self.store)
        self.assertEqual([row['amount'] for row in result['versions']], ['120'])
        self.assertTrue(result['simulator'])

    def test_explicit_seed_demo_adds_fictional_history_idempotently(self):
        result = m24.run(m24.SPEC['defaults'] | {
            'action': 'seed_demo', 'confirmed_by': '架空デモ担当',
        }, self.store)
        self.assertEqual([row['amount'] for row in result['versions']], ['110', '120'])
        self.assertEqual([row['valid_from'] for row in result['versions']],
                         ['2026-08-01', '2026-10-11'])
        self.assertEqual(result['versions'][0]['checked_at'], '2026-08-02')
        self.assertEqual(result['versions'][0]['source'], 'simulator:架空価格履歴')
        self.assertTrue(result['simulator'])
        self.assertIn('相場を代表する値ではありません', result['comparison'])
        self.assertEqual(len(self.store.price_versions('demo-paint')), 2)
        m24.run(m24.SPEC['defaults'] | {
            'action': 'seed_demo', 'confirmed_by': '架空デモ担当',
        }, self.store)
        self.assertEqual(len(self.store.price_versions('demo-paint')), 2)

    def test_read_only_timeline_does_not_seed_and_preserves_expiry(self):
        payload = {'action': 'timeline', 'item_id': 'demo-paint', 'unit': 'ml',
                   'price_type': '販売'}
        result = m24.run(payload, self.store)
        self.assertEqual(result['versions'], [])
        self.assertTrue(result['unknowns'])
        self.assertEqual(self.store.price_versions(), [])

        item = demo_item(unit_price='105')
        self.store.add_price(item, '担当A', valid_from='2026-01-01',
                             valid_until='2026-03-01', source='納品書A',
                             checked_at='2026-01-02')
        result = m24.run(payload, self.store)
        self.assertEqual(result['versions'][0]['valid_until'], '2026-03-01')
        self.assertEqual(result['versions'][0]['checked_at'], '2026-01-02')
        self.assertEqual(result['versions'][0]['confirmed_by'], '担当A')

    def test_other_units_types_suppliers_and_conditions_are_separate_groups(self):
        base = demo_item(item_id='paint-x', price_type='仕入', unit_price='80')
        self.store.add_price(base, '担当A', supplier_id='supplier-a', valid_from='2026-01-01',
                             source='仕入先A', transaction_conditions={'freight_basis': 'included'})
        self.store.add_price({**base, 'unit_price': '90'}, '担当A', supplier_id='supplier-b',
                             valid_from='2026-01-02', source='仕入先B',
                             transaction_conditions={'freight_basis': 'included'})
        self.store.add_price({**base, 'unit_price': '95'}, '担当A', supplier_id='supplier-a',
                             valid_from='2026-01-03', source='別送料',
                             transaction_conditions={'freight_basis': 'excluded'})
        result = m24.run({
            'action': 'timeline', 'item_id': 'paint-x', 'unit': 'ml',
            'price_type': '仕入', 'supplier_id': 'supplier-a',
            'transaction_conditions': {'freight_basis': 'included'},
        }, self.store)
        self.assertEqual([row['amount'] for row in result['versions']], ['80'])
        self.assertEqual(len(result['incomparable_groups']), 2)
        self.assertTrue(all('比較対象外' in group['reason']
                            for group in result['incomparable_groups']))
        self.assertTrue(all(row['unit'] == 'ml' for row in result['versions']))
        with self.assertRaisesRegex(ValidationError, '基準単位'):
            self.store.add_price({**base, 'unit': 'g'}, '担当A', supplier_id='supplier-a',
                                 valid_from='2026-01-04')

    def test_invalid_filter_and_unsupported_actions_fail(self):
        with self.assertRaises(ValidationError):
            m24.run({'action': 'timeline', 'item_id': 'demo-paint', 'unit': 'ml',
                     'price_type': '粗利'}, self.store)
        with self.assertRaises(ValidationError):
            m24.run({'action': 'timeline', 'item_id': 'demo-paint', 'unit': 'ml',
                     'price_type': '販売', 'unexpected': True}, self.store)
        with self.assertRaises(ValidationError):
            m24.run({'action': 'unknown'}, self.store)


if __name__ == '__main__':
    unittest.main()
