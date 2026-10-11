"""M30 quote-time price snapshot tests."""

import unittest

from auto_repair_items.core import DEMO_DATE, ITEM_FIELDS, Store, ValidationError, demo_item
from auto_repair_items.m30 import QUOTE_NAMESPACE, SPEC, run


class M30Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.add_price()

    def tearDown(self):
        self.store.close()

    def add_price(self, *, price='120', status='approved', unit='ml', supplier='supplier-a',
                  valid_from=DEMO_DATE, valid_until=None, conditions=None):
        item = demo_item('paint-a', '販売', price, unit)
        metadata = conditions or {'freight_basis': 'included', 'currency': 'JPY',
                                  'transaction_conditions': '架空の店頭渡し'}
        return self.store.add_price(item, '価格承認者', supplier_id=supplier,
                                    valid_from=valid_from, valid_until=valid_until,
                                    status=status, **metadata)

    def payload(self, **changes):
        payload = {
            'action': 'save', 'quote_id': 'quote-a', 'confirmed_by': '見積担当',
            'as_of': DEMO_DATE,
            'lines': [{'quote_line_id': 'line-a', 'item_id': 'paint-a', 'quantity': '2.5',
                       'unit': 'ml', 'price_type': '販売', 'supplier_id': 'supplier-a',
                       'conditions': {'freight_basis': 'included', 'currency': 'JPY',
                                      'transaction_conditions': '架空の店頭渡し'}}],
        }
        payload.update(changes)
        return payload

    def test_save_fixes_selected_approved_price_metadata_and_common_items(self):
        result = run(self.payload(), self.store)
        quote = result['quote']
        line = quote['lines'][0]

        self.assertEqual(line['unit_price_snapshot'], '120')
        self.assertEqual(line['quantity'], '2.5')
        self.assertEqual(line['line_total'], '300.0')
        self.assertEqual(line['price_version_id'], self.store.price_versions('paint-a')[0]['price_version_id'])
        self.assertEqual(line['source_snapshot'], 'simulator:架空値')
        self.assertEqual(line['conditions']['currency'], 'JPY')
        self.assertEqual(set(result['items'][0]), set(ITEM_FIELDS))
        self.assertEqual(self.store.latest(QUOTE_NAMESPACE, 'quote-a'), quote)

    def test_master_price_update_does_not_change_saved_quote_and_get_replays_it(self):
        saved = run(self.payload(), self.store)['quote']
        newer = demo_item('paint-a', '販売', '150', 'ml')
        self.store.add_price(newer, '価格承認者', supplier_id='supplier-a',
                             transaction_conditions='架空の店頭渡し',
                             freight_basis='included', currency='JPY')

        fetched = run({'action': 'get', 'quote_id': 'quote-a'}, self.store)['quote']
        self.assertEqual(fetched, saved)
        self.assertEqual(fetched['lines'][0]['unit_price_snapshot'], '120')
        self.assertEqual(run({'action': 'list', 'query': 'quote-a'}, self.store)['quotes'], [saved])

    def test_duplicate_quote_id_is_rejected_without_appending(self):
        run(self.payload(), self.store)
        before = self.store.records(QUOTE_NAMESPACE, 'quote-a')
        with self.assertRaises(ValidationError):
            run(self.payload(), self.store)
        self.assertEqual(self.store.records(QUOTE_NAMESPACE, 'quote-a'), before)

    def test_price_approval_expiry_unit_supplier_and_conditions_are_checked(self):
        scenarios = (
            (dict(status='pending'), self.payload()),
            (dict(valid_from='2026-08-01', valid_until='2026-10-10'), self.payload()),
            (dict(unit='L'), self.payload()),
            (dict(supplier='supplier-b'), self.payload()),
            (dict(), self.payload(lines=[dict(self.payload()['lines'][0], quantity='0')])),
            (dict(), self.payload(lines=[dict(self.payload()['lines'][0],
                                                 conditions={'freight_basis': 'excluded'})])),
        )
        for index, (price_options, payload) in enumerate(scenarios):
            with self.subTest(index=index):
                store = Store()
                try:
                    self.add_to(store, **price_options)
                    payload['quote_id'] = f'bad-{index}'
                    with self.assertRaises(ValidationError):
                        run(payload, store)
                    self.assertEqual(store.records(QUOTE_NAMESPACE, f'bad-{index}'), [])
                finally:
                    store.close()

    def add_to(self, store, **options):
        item = demo_item('paint-a', '販売', options.pop('price', '120'), options.pop('unit', 'ml'))
        metadata = options.pop('conditions', None) or {
            'freight_basis': 'included', 'currency': 'JPY',
            'transaction_conditions': '架空の店頭渡し',
        }
        store.add_price(item, '価格承認者', supplier_id=options.pop('supplier', 'supplier-a'),
                        valid_from=options.pop('valid_from', DEMO_DATE),
                        valid_until=options.pop('valid_until', None),
                        status=options.pop('status', 'approved'), **metadata)

    def test_demo_seeds_only_on_explicit_demo_action(self):
        self.store.close()
        self.store = Store()
        self.assertEqual(self.store.price_versions('demo-m30-paint'), [])
        result = run(SPEC['defaults'], self.store)
        self.assertTrue(result['simulator'])
        self.assertEqual(result['quote']['lines'][0]['unit_price_snapshot'], '120')
        self.assertEqual(len(self.store.price_versions('demo-m30-paint')), 1)


if __name__ == '__main__':
    unittest.main()
