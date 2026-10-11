"""M27 price delta comparison tests."""

import unittest

from auto_repair_items.core import DEMO_DATE, Store, ValidationError, demo_item
from auto_repair_items.m27 import QUOTE_NAMESPACE, SPEC, run


class M27Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def save_quote(self, *, unit='ml', price_type='販売', supplier_id='supplier-a', conditions=None,
                   quote_id='quote-a', item_id='paint-a'):
        conditions = {'freight_basis': 'included'} if conditions is None else conditions
        return self.store.put(QUOTE_NAMESPACE, {
            'quote_id': quote_id, 'confirmed_by': '見積担当', 'created_at': '2026-08-01T09:00:00+09:00',
            'lines': [{
                'quote_line_id': 'line-a', 'item_id': item_id, 'name': '塗料', 'category': '塗料',
                'quantity': '2', 'unit': unit, 'unit_price_snapshot': '100.25',
                'price_type': price_type, 'price_version_id': 'old-price-v1',
                'source_snapshot': 'manual:見積入力', 'updated_at': '2026-08-01',
                'supplier_id': supplier_id, 'conditions': conditions, 'line_total': '200.5',
            }],
        }, record_id=quote_id)

    def add_current_price(self, *, amount='125.5', unit='ml', price_type='販売', supplier_id='supplier-a',
                          conditions=None, valid_from=DEMO_DATE):
        item = demo_item(item_id='paint-a', unit=unit, price_type=price_type, unit_price=amount)
        return self.store.add_price(item, '価格確認者', supplier_id=supplier_id, valid_from=valid_from,
                                    transaction_conditions=conditions or {'freight_basis': 'included'})

    def payload(self, **selection_changes):
        selection = {'item_id': 'paint-a', 'unit': 'ml', 'price_type': '販売',
                     'supplier_id': 'supplier-a', 'conditions': {'freight_basis': 'included'}}
        selection.update(selection_changes)
        return {'action': 'compare', 'quote_id': 'quote-a', 'basket': [selection],
                'as_of': DEMO_DATE, 'confirmed_by': '見積担当'}

    def test_compare_returns_decimal_delta_without_changing_quote_or_prices(self):
        original = self.save_quote()
        current = self.add_current_price()
        before_prices = self.store.price_versions()

        result = run(self.payload(), self.store)

        self.assertEqual(result['comparisons'], [{
            'item_id': 'paint-a', 'status': 'comparable', 'previous_unit_price': '100.25',
            'current_unit_price': '125.5', 'difference': '25.25',
            'previous_price_version_id': 'old-price-v1', 'current_price_version_id': current['price_version_id'],
            'unit': 'ml', 'price_type': '販売', 'supplier_id': 'supplier-a',
            'conditions': {'freight_basis': 'included'},
        }])
        self.assertFalse(result['price_finalized'])
        self.assertEqual(self.store.latest(QUOTE_NAMESPACE, 'quote-a'), original)
        self.assertEqual(self.store.price_versions(), before_prices)
        self.assertEqual(self.store.records('m27_price_comparison'), [])

    def test_explicit_demo_creates_fictional_previous_quote_and_prices(self):
        result = run(SPEC['defaults'], self.store)

        self.assertTrue(result['simulator'])
        self.assertEqual(result['comparisons'][0]['difference'], '20')
        self.assertEqual(len(self.store.price_versions('demo-m27-paint')), 2)
        snapshot = self.store.latest(QUOTE_NAMESPACE, 'demo-m27-quote')
        self.assertTrue(snapshot['simulator'])
        self.assertEqual(snapshot['lines'][0]['unit_price_snapshot'], '100')
        self.assertEqual(len(self.store.records(QUOTE_NAMESPACE, 'demo-m27-quote')), 1)

    def test_mismatched_conditions_or_missing_price_are_comparison_unavailable(self):
        self.save_quote()
        self.add_current_price(conditions={'freight_basis': 'excluded'})
        result = run(self.payload(), self.store)
        self.assertEqual(result['comparisons'][0]['status'], 'comparison_unavailable')

        no_price_store = Store()
        try:
            no_price_store.put(QUOTE_NAMESPACE, {
                'quote_id': 'quote-a', 'lines': self.store.latest(QUOTE_NAMESPACE, 'quote-a')['lines'],
            }, record_id='quote-a')
            self.save_quote()
            result = run(self.payload(), no_price_store)
            self.assertEqual(result['comparisons'][0]['status'], 'comparison_unavailable')
        finally:
            no_price_store.close()

    def test_unit_type_and_supplier_mismatches_are_not_compared(self):
        self.save_quote()
        self.add_current_price()
        for patch in ({'unit': 'g'}, {'price_type': '仕入'}, {'supplier_id': 'supplier-b'},
                      {'conditions': {'freight_basis': 'excluded'}}):
            with self.subTest(patch=patch):
                result = run(self.payload(**patch), self.store)
                self.assertEqual(result['comparisons'][0]['status'], 'comparison_unavailable')

    def test_invalid_basket_or_confirmation_stops(self):
        self.save_quote()
        for changes in ({'basket': []}, {'confirmed_by': ''}, {'as_of': 'not-a-date'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                run(self.payload() | changes, self.store)


if __name__ == '__main__':
    unittest.main()
