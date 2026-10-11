"""M14 price freshness display tests."""

import unittest

from auto_repair_items import m14
from auto_repair_items.core import Store, ValidationError, demo_item


class M14Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_defaults_seed_fictional_price_and_show_human_age_separately(self):
        result = m14.run(m14.SPEC['defaults'], self.store)

        self.assertEqual(result['status'], '確認済み')
        self.assertEqual(result['human_checked_at'], '2026-10-11')
        self.assertEqual(result['elapsed_days'], 0)
        self.assertEqual(result['source_updated_at'], '2026-10-11')
        self.assertTrue(result['simulator'])
        self.assertEqual(len(self.store.price_versions('demo-m14-paint', '仕入')), 1)

    def test_checked_at_is_used_and_source_updated_at_is_not_mistaken_for_review(self):
        item = demo_item('m14-example', '仕入', '731', '個')
        self.store.add_price(item, '架空担当', checked_at='2026-10-01',
                             source_updated_at='2026-10-09')

        result = m14.run({'item_id': 'm14-example', 'price_type': '仕入',
                          'as_of': '2026-10-11'}, self.store)

        self.assertEqual(result['human_checked_at'], '2026-10-01')
        self.assertEqual(result['elapsed_days'], 10)
        self.assertEqual(result['source_updated_at'], '2026-10-09')
        self.assertEqual(self.store.get_price('m14-example', '仕入')['item']['unit_price'], '731')

    def test_missing_checked_at_is_unconfirmed_even_when_item_updated_at_exists(self):
        self.store.add_price(demo_item('m14-unchecked', '仕入', '500'), '架空担当')

        result = m14.run({'item_id': 'm14-unchecked', 'price_type': '仕入'}, self.store)

        self.assertEqual(result['status'], '未確認')
        self.assertIsNone(result['human_checked_at'])
        self.assertIsNone(result['elapsed_days'])
        self.assertEqual(result['source_updated_at'], '2026-10-11')

    def test_future_human_or_source_date_is_an_error(self):
        self.store.add_price(demo_item('m14-future', '仕入', '500'), '架空担当',
                             checked_at='2026-10-12', source_updated_at='2026-10-11')
        with self.assertRaisesRegex(ValidationError, 'checked_at.*未来'):
            m14.run({'item_id': 'm14-future', 'price_type': '仕入', 'as_of': '2026-10-11'}, self.store)

        self.store.add_price(demo_item('m14-future-source', '仕入', '500'), '架空担当',
                             checked_at='2026-10-10', source_updated_at='2026-10-12')
        with self.assertRaisesRegex(ValidationError, 'source_updated_at.*未来'):
            m14.run({'item_id': 'm14-future-source', 'price_type': '仕入', 'as_of': '2026-10-11'}, self.store)

    def test_missing_price_and_invalid_inputs_fail(self):
        with self.assertRaises(ValidationError):
            m14.run({'item_id': 'not-found'}, self.store)
        with self.assertRaises(ValidationError):
            m14.run({'item_id': 'x', 'price_type': 'bad'}, self.store)
        with self.assertRaises(ValidationError):
            m14.run({'item_id': 'x', 'unknown': True}, self.store)


if __name__ == '__main__':
    unittest.main()
