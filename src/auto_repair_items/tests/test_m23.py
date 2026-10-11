"""M23 tests for append-only quote quantity comparisons."""

import unittest

from auto_repair_items.core import Store, ValidationError
from auto_repair_items.m23 import QUOTE_NAMESPACE, SPEC, USAGE_NAMESPACE, run


class M23Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def save_quote(self, *, quantity='10', quote_id='quote-a', quote_line_id='line-a'):
        snapshot = {
            'quote_id': quote_id,
            'confirmed_by': '見積担当', 'created_at': '2026-10-11T09:00:00+09:00',
            'lines': [{
                'quote_line_id': quote_line_id, 'item_id': 'paint-a',
                'name': '塗料', 'category': '塗料', 'quantity': quantity,
                'unit': 'ml', 'unit_price_snapshot': '120',
                'price_type': '販売', 'price_version_id': 'price-v1',
                'source_snapshot': 'manual:見積入力', 'updated_at': '2026-10-11',
                'supplier_id': '', 'conditions': {}, 'line_total': '1200',
            }],
        }
        return self.store.put(QUOTE_NAMESPACE, snapshot, record_id=quote_id)

    def test_explicit_demo_default_records_fictional_example_without_price_seed(self):
        result = run(SPEC['defaults'], self.store)

        usage = result['item_usage']
        self.assertTrue(result['simulator'])
        self.assertEqual(result['comparison'], {
            'estimated_qty': '15', 'actual_qty': '12.5', 'difference': '-2.5', 'unit': 'ml',
        })
        self.assertEqual(usage['confirmed_by'], '架空デモ担当')
        self.assertTrue(usage['recorded_at'])
        self.assertEqual(self.store.price_versions(), [])
        self.assertEqual(self.store.latest(QUOTE_NAMESPACE, 'demo-m23-quote')['lines'][0]['quantity'], '15')

    def test_record_compares_decimal_quantities_and_keeps_quote_unchanged(self):
        original = self.save_quote(quantity='1.250')
        before_prices = self.store.price_versions()
        result = run({
            'action': 'record', 'quote_id': 'quote-a', 'quote_line_id': 'line-a',
            'actual_qty': '2.75', 'reason': '余分に塗布した', 'confirmed_by': '整備士A',
        }, self.store)

        usage = result['item_usage']
        self.assertEqual(result['comparison']['difference'], '1.500')
        self.assertEqual(usage['estimated_qty'], '1.250')
        self.assertEqual(usage['actual_qty'], '2.75')
        self.assertEqual(usage['reason'], '余分に塗布した')
        self.assertEqual(usage['confirmed_by'], '整備士A')
        self.assertTrue(usage['recorded_at'])
        self.assertEqual(self.store.latest(QUOTE_NAMESPACE, 'quote-a'), original)
        self.assertEqual(self.store.price_versions(), before_prices)
        self.assertEqual(len(self.store.records(USAGE_NAMESPACE)), 1)

    def test_missing_quote_or_line_and_invalid_values_do_not_save_usage(self):
        common = {'action': 'record', 'quote_id': 'quote-a', 'quote_line_id': 'line-a',
                  'actual_qty': '2', 'reason': '確認済み', 'confirmed_by': '担当'}
        with self.assertRaises(ValidationError):
            run(common, self.store)
        self.save_quote()
        for changes in (
            {'quote_line_id': 'missing'}, {'actual_qty': '-1'},
            {'reason': ''}, {'confirmed_by': ''},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                run({**common, **changes}, self.store)
        self.assertEqual(self.store.records(USAGE_NAMESPACE), [])

    def test_list_filters_records_without_mutating_snapshot_or_prices(self):
        self.save_quote()
        self.save_quote(quote_id='quote-b', quote_line_id='line-b')
        for quote_id, quote_line_id in (('quote-a', 'line-a'), ('quote-b', 'line-b')):
            run({'action': 'record', 'quote_id': quote_id, 'quote_line_id': quote_line_id,
                 'actual_qty': '8', 'reason': '記録', 'confirmed_by': '担当'}, self.store)
        before_snapshots = self.store.records(QUOTE_NAMESPACE)
        before_prices = self.store.price_versions()

        result = run({'action': 'list', 'quote_id': 'quote-a'}, self.store)

        self.assertEqual(len(result['item_usages']), 1)
        self.assertEqual(result['item_usages'][0]['quote_line_id'], 'line-a')
        self.assertEqual(self.store.records(QUOTE_NAMESPACE), before_snapshots)
        self.assertEqual(self.store.price_versions(), before_prices)


if __name__ == '__main__':
    unittest.main()
