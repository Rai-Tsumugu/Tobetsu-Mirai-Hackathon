"""M18 conditional-price tests."""

import unittest

from auto_repair_items import m18
from auto_repair_items.core import Store, ValidationError


class M18Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_defaults_seed_and_return_a_conditional_quote_candidate(self):
        result = m18.run(m18.SPEC['defaults'], self.store)
        self.assertEqual(result['quote_candidate']['unit_price'], '6800')
        self.assertEqual(result['quote_candidate']['status'], '条件一致')
        self.assertTrue(result['simulator'])
        self.assertEqual(self.store.price_versions(), [])
        self.assertEqual(len(self.store.records('conditional_price')), 1)
        self.assertNotIn('items', result)

    def test_record_saves_all_terms_in_separate_namespace(self):
        result = m18.run({
            'action': 'record', 'item_id': 'part-1', 'unit_price': '4321.50', 'min_qty': '4',
            'unit': '個', 'valid_from': '2026-10-01', 'valid_until': '2026-10-31',
            'price_type': '仕入', 'source': '仕入先見積書', 'confirmed_by': '担当A',
        }, self.store)
        saved = self.store.latest('conditional_price', result['conditional_price_id'])
        self.assertEqual(saved['unit_price'], '4321.50')
        self.assertEqual(saved['min_qty'], '4')
        self.assertEqual(saved['source'], '仕入先見積書')
        self.assertEqual(saved['confirmed_by'], '担当A')
        self.assertEqual(self.store.price_versions(), [])

    def test_each_term_must_match_and_list_shows_evidence(self):
        self._record()
        for overrides in (
            {'quantity': '2'}, {'unit': '箱'}, {'as_of': '2026-11-01'},
            {'price_type': '販売'},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                m18.run({'action': 'apply', 'item_id': 'part-1', 'quantity': '5',
                         'unit': '個', 'price_type': '仕入', 'as_of': '2026-10-15', **overrides}, self.store)
        listed = m18.run({'action': 'list', 'item_id': 'part-1', 'quantity': '5',
                          'unit': '個', 'price_type': '仕入', 'as_of': '2026-10-15'}, self.store)
        candidate = listed['conditional_prices'][0]
        self.assertEqual(candidate['status'], '条件一致')
        self.assertEqual(candidate['source'], '見積書')
        self.assertEqual(candidate['valid_until'], '2026-10-31')
        self.assertEqual(candidate['confirmed_by'], '担当A')

    def test_missing_fields_bad_ranges_and_non_purchase_prices_stop(self):
        base = {'action': 'record', 'item_id': 'part-2', 'unit_price': '100', 'min_qty': '2',
                'unit': '個', 'valid_from': '2026-10-10', 'valid_until': '2026-10-01',
                'price_type': '仕入', 'source': '見積書', 'confirmed_by': '担当A'}
        with self.assertRaisesRegex(ValidationError, '開始日より前'):
            m18.run(base, self.store)
        with self.assertRaisesRegex(ValidationError, '仕入価格のみ'):
            m18.run({**base, 'valid_until': '2026-10-31', 'price_type': '販売'}, self.store)
        with self.assertRaises(ValidationError):
            m18.run({**base, 'valid_until': '2026-10-31', 'source': ''}, self.store)
        with self.assertRaises(ValidationError):
            m18.run({**base, 'valid_until': '2026-10-31', 'min_qty': '0'}, self.store)

    def _record(self):
        return m18.run({
            'action': 'record', 'item_id': 'part-1', 'unit_price': '4321.50', 'min_qty': '4',
            'unit': '個', 'valid_from': '2026-10-01', 'valid_until': '2026-10-31',
            'price_type': '仕入', 'source': '見積書', 'confirmed_by': '担当A',
        }, self.store)


if __name__ == '__main__':
    unittest.main()
