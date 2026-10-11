"""Acceptance tests for M01 paint-code normalization and lookup."""

import tempfile
import unittest
from pathlib import Path

from auto_repair_items import m01
from auto_repair_items.core import Store, ValidationError, demo_item, seed_demo


class M01Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        seed_demo(self.store)

    def tearDown(self):
        self.store.close()

    def payload(self, **changes):
        result = dict(m01.SPEC['defaults'])
        result.update(changes)
        return result

    def add_paint(self, item_id, *, price_type='販売', amount='100'):
        item = demo_item(item_id=item_id, price_type=price_type, unit_price=amount)
        item['name'] = '架空塗料 ' + item_id
        self.store.add_price(item, '架空デモ担当')

    def test_spec_defaults_run_after_demo_seed(self):
        result = m01.run(m01.SPEC['defaults'], self.store)

        self.assertEqual(result['status'], 'approved')
        self.assertEqual(result['paint_code']['raw_code'], 'DEMO-001')
        self.assertEqual(result['paint_code']['normalized_code'], 'DEMO-001')
        self.assertEqual(result['items'][0]['item_id'], 'demo-paint')
        self.assertEqual(
            set(result['items'][0]),
            {'item_id', 'name', 'category', 'unit', 'unit_price', 'price_type', 'source', 'updated_at'},
        )

    def test_nfkc_and_case_normalize_while_raw_code_is_preserved(self):
        result = m01.run(self.payload(raw_code='  ａｂ-１２  '), self.store)

        self.assertEqual(result['paint_code']['raw_code'], '  ａｂ-１２  ')
        self.assertEqual(result['paint_code']['normalized_code'], 'AB-12')

    def test_lookup_requires_same_raw_code_and_returns_common_item(self):
        registration = m01.run(self.payload(), self.store)
        result = m01.run(self.payload(action='lookup'), self.store)

        self.assertEqual(result['items'], [registration['item']])
        with self.assertRaisesRegex(ValidationError, '原表記'):
            m01.run(self.payload(action='lookup', raw_code='demo-001'), self.store)

    def test_normalized_collision_remains_pending_and_not_quoteable(self):
        self.add_paint('paint-upper')
        self.add_paint('paint-lower')
        first = m01.run(self.payload(item_id='paint-upper', raw_code='AB-9'), self.store)
        second_payload = self.payload(item_id='paint-lower', raw_code='ab-9')
        second = m01.run(second_payload, self.store)

        self.assertEqual(first['status'], 'approved')
        self.assertEqual(second['status'], 'pending')
        self.assertEqual(second['items'], [])
        # Repeating either colliding spelling cannot approve the contested code.
        self.assertEqual(m01.run(second_payload, self.store)['status'], 'pending')
        with self.assertRaises(ValidationError):
            m01.run(self.payload(action='lookup', raw_code='AB-9'), self.store)

    def test_code_without_clear_token_is_rejected_before_mapping(self):
        for code in ('   ', '---', 'A B', 'A\nB'):
            with self.subTest(code=code), self.assertRaises(ValidationError):
                m01.run(self.payload(raw_code=code), self.store)
        self.assertEqual(self.store.records('paint_code'), [])

    def test_requires_existing_approved_paint_price(self):
        with self.assertRaisesRegex(ValidationError, '価格未確認'):
            m01.run(self.payload(item_id='missing-item'), self.store)
        with self.assertRaisesRegex(ValidationError, 'category'):
            part_item = demo_item(item_id='part-1', price_type='販売', unit_price='50')
            part_item.update(name='架空部品', category='部品')
            self.store.add_price(part_item, '架空デモ担当')
            m01.run(self.payload(item_id='part-1'), self.store)
        self.assertEqual(self.store.records('paint_code'), [])

    def test_price_type_is_respected_and_purchase_is_not_substituted(self):
        self.store.add_price(demo_item(price_type='仕入', unit_price='80'), '架空デモ担当')
        result = m01.run(self.payload(price_type='仕入'), self.store)
        self.assertEqual(result['item']['price_type'], '仕入')
        self.assertEqual(result['item']['unit_price'], '80')

    def test_mapping_persists_in_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'items.sqlite3'
            store = Store(database)
            seed_demo(store)
            registered = m01.run(m01.SPEC['defaults'], store)
            store.close()

            reopened = Store(database)
            try:
                result = m01.run(m01.SPEC['defaults'] | {'action': 'lookup'}, reopened)
                self.assertEqual(result['paint_code'], registered['paint_code'])
                self.assertEqual(result['items'][0]['unit_price'], '120')
            finally:
                reopened.close()

    def test_invalid_action_and_payload_are_rejected(self):
        for payload in (None, [], self.payload(action='guess')):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                m01.run(payload, self.store)


if __name__ == '__main__':
    unittest.main()
