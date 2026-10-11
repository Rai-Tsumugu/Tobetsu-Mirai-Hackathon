"""Acceptance tests for M07 single-item registration and catalog search."""

import tempfile
import unittest
from pathlib import Path

from auto_repair_items import m07
from auto_repair_items.core import DEMO_DATE, ITEM_FIELDS, Store, ValidationError, seed_demo


class M07Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        seed_demo(self.store)

    def tearDown(self):
        self.store.close()

    def payload(self, **changes):
        result = dict(m07.SPEC['defaults'])
        result.update(changes)
        return result

    def test_spec_defaults_register_against_seeded_store(self):
        result = m07.run(m07.SPEC['defaults'], self.store)

        self.assertEqual(result['status'], 'approved')
        self.assertEqual(result['item']['item_id'], 'demo-m07-brake-pad')
        self.assertEqual(set(result['items'][0]), set(ITEM_FIELDS))
        self.assertEqual(result['confirmed_by'], '架空デモ担当')
        self.assertEqual(result['currency'], 'JPY')
        saved = self.store.price_versions('demo-m07-brake-pad', '販売')
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['confirmed_by'], '架空デモ担当')

    def test_search_and_list_return_common_items_and_apply_filters(self):
        registered = m07.run(self.payload(), self.store)

        all_items = m07.run({'action': 'list', 'as_of': DEMO_DATE}, self.store)
        self.assertEqual(all_items['count'], 3)
        self.assertTrue(all(set(item) == set(ITEM_FIELDS) for item in all_items['items']))

        filtered = m07.run({
            'action': 'search', 'as_of': DEMO_DATE, 'query': 'brake',
            'category_filter': '部品', 'price_type_filter': '販売',
        }, self.store)
        self.assertEqual(filtered['count'], 1)
        self.assertEqual(filtered['items'], [registered['item']])

    def test_missing_required_values_reject_without_persisting(self):
        for field, value in (
            ('item_id', ''), ('name', ' '), ('category', 'その他'), ('unit', ''),
            ('unit_price', None), ('price_type', '原価'), ('source', ''),
            ('updated_at', 'not-a-date'), ('confirmed_by', ''),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                m07.run(self.payload(**{field: value}), self.store)
        self.assertEqual(self.store.price_versions('demo-m07-brake-pad'), [])

    def test_bad_price_and_expiry_are_rejected_without_persistence(self):
        for changes in (
            {'unit_price': '-1'}, {'unit_price': 'NaN'},
            {'valid_from': '2026-10-12', 'valid_until': '2026-10-11'},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                m07.run(self.payload(**changes), self.store)
        self.assertEqual(self.store.price_versions('demo-m07-brake-pad'), [])

    def test_pending_and_expired_prices_are_not_searchable(self):
        item = dict(self.payload())
        item.update(item_id='pending-part', status='pending')
        self.store.add_price({key: item[key] for key in ITEM_FIELDS}, '架空担当', status='pending')
        expired_item = {key: item[key] for key in ITEM_FIELDS}
        expired_item.update(item_id='expired-part', updated_at='2026-10-01')
        self.store.add_price(
            expired_item, '架空担当', valid_from='2026-10-01', valid_until='2026-10-10',
        )

        result = m07.run({'action': 'search', 'query': 'part'}, self.store)

        self.assertEqual(result['items'], [])

    def test_persisted_price_remains_available_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'items.sqlite3'
            store = Store(database)
            try:
                result = m07.run(m07.SPEC['defaults'], store)
                expected = result['item']
            finally:
                store.close()

            reopened = Store(database)
            try:
                search = m07.run({
                    'action': 'search', 'query': 'demo-m07-brake-pad', 'as_of': DEMO_DATE,
                }, reopened)
                self.assertEqual(search['items'], [expected])
            finally:
                reopened.close()

    def test_invalid_action_payload_and_search_filters_are_rejected(self):
        for payload in (None, [], {'action': 'delete'}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                m07.run(payload, self.store)
        for payload in (
            {'action': 'search', 'category_filter': '工賃'},
            {'action': 'search', 'price_type_filter': '掛率'},
            {'action': 'search', 'query': 10},
            {'action': 'search', 'as_of': 'invalid'},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                m07.run(payload, self.store)


if __name__ == '__main__':
    unittest.main()
