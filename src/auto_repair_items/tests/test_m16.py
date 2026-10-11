"""M16 freshness queue tests."""

import unittest

from auto_repair_items import m16
from auto_repair_items.core import DEMO_DATE, Store, ValidationError, demo_item, seed_demo


class M16Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_defaults_seed_a_fictional_unconfirmed_expired_price(self):
        seed_demo(self.store)
        result = m16.run(m16.SPEC['defaults'], self.store)

        self.assertEqual({row['item_id'] for row in result['queue']}, {'demo-paint'})
        self.assertTrue(all(row['reason'] == '未確認' for row in result['queue']))
        self.assertTrue(all(row['status'] == '未対応' for row in result['queue']))
        self.assertTrue(all(row['checked_at'] is None for row in result['queue']))
        self.assertTrue(result['simulator'])

    def test_list_does_not_create_prices_as_a_side_effect(self):
        m16.run(m16.SPEC['defaults'], self.store)
        self.assertEqual(self.store.price_versions(), [])

    def test_priority_order_is_expired_then_unconfirmed_then_difference(self):
        self.store.add_price(demo_item('z-diff', '仕入', '100'), '架空担当',
                             checked_at='2026-10-10')
        self.store.add_price(demo_item('z-diff', '仕入', '120'), '架空担当',
                             checked_at='2026-10-10')
        self.store.add_price(demo_item('b-unconfirmed', '仕入', '50'), '架空担当')
        item = demo_item('a-expired', '仕入', '70')
        item['updated_at'] = '2026-10-01'
        self.store.add_price(item, '架空担当', valid_from='2026-10-01',
                             valid_until='2026-10-10', checked_at='2026-10-01')

        result = m16.run({'as_of': DEMO_DATE}, self.store)

        self.assertEqual([row['reason'] for row in result['queue']],
                         ['期限切れ', '未確認', '差分あり'])
        self.assertEqual([row['priority'] for row in result['queue']], [0, 1, 2])

    def test_status_update_keeps_price_and_records_person_reason_and_checked_at(self):
        original = self.store.add_price(demo_item('part-a', '仕入', '845'), '登録者')

        result = m16.run({
            'action': 'update_status', 'item_id': 'part-a', 'price_type': '仕入',
            'status': '確認済み', 'confirmed_by': '担当者A', 'reason': '納品書と照合',
            'checked_at': '2026-10-10', 'as_of': DEMO_DATE,
        }, self.store)

        versions = self.store.price_versions('part-a', '仕入')
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[-1]['item']['unit_price'], '845')
        self.assertEqual(versions[0]['price_version_id'], original['price_version_id'])
        self.assertEqual(versions[-1]['metadata']['checked_at'], '2026-10-10')
        self.assertEqual(result['confirmed_by'], '担当者A')
        self.assertEqual(result['reason'], '納品書と照合')
        self.assertEqual(result['unit_price'], '845')
        self.assertNotIn('part-a', {row['item_id'] for row in
                                    m16.run({'as_of': DEMO_DATE}, self.store)['queue']})

        self.store.add_price(demo_item('part-a', '仕入', '900'), '別担当',
                             checked_at=DEMO_DATE)
        self.assertIn('part-a', {row['item_id'] for row in
                                 m16.run({'as_of': DEMO_DATE}, self.store)['queue']})

    def test_needs_research_retains_state_and_reason_without_changing_price(self):
        self.store.add_price(demo_item('part-b', '販売', '990'), '登録者')

        result = m16.run({
            'action': 'update_status', 'item_id': 'part-b', 'price_type': '販売',
            'status': '要調査', 'confirmed_by': '担当者B', 'reason': '出所へ照会中',
        }, self.store)

        row = next(row for row in m16.run({'as_of': DEMO_DATE}, self.store)['queue']
                   if row['item_id'] == 'part-b')
        self.assertEqual(result['unit_price'], '990')
        self.assertEqual(len(self.store.price_versions('part-b', '販売')), 1)
        self.assertEqual(row['status'], '要調査')
        self.assertEqual(row['confirmed_by'], '担当者B')
        self.assertEqual(row['review_reason'], '出所へ照会中')

    def test_invalid_review_inputs_and_future_checked_date_fail(self):
        self.store.add_price(demo_item('part-c', '仕入', '10'), '登録者')
        common = {'action': 'update_status', 'item_id': 'part-c', 'status': '確認済み',
                  'confirmed_by': '担当者', 'reason': '確認'}
        for changes in ({'status': '価格更新'}, {'confirmed_by': ''}, {'reason': ' '}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                m16.run({**common, **changes}, self.store)
        with self.assertRaisesRegex(ValidationError, 'checked_at.*未来'):
            m16.run({**common, 'checked_at': '2026-10-12', 'as_of': DEMO_DATE}, self.store)
        self.assertEqual(len(self.store.price_versions('part-c', '仕入')), 1)


if __name__ == '__main__':
    unittest.main()
