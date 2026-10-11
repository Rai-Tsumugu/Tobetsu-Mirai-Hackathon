"""M25 raw-material index reference card tests."""

import unittest

from auto_repair_items import m25
from auto_repair_items.core import Store, ValidationError, demo_item


class M25Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_explicit_demo_seed_lists_fictional_observation_and_keeps_terms_unconfirmed(self):
        result = m25.run(m25.SPEC['defaults'], self.store)

        self.assertEqual(len(result['observations']), 1)
        row = result['observations'][0]
        self.assertEqual(row['source'], 'simulator:架空データ出典')
        self.assertEqual(row['series'], '架空ナフサ指数')
        self.assertEqual(row['value'], '123.4')
        self.assertEqual(row['unit'], '指数ポイント')
        self.assertEqual(row['published_at'], '2026-10-01')
        self.assertEqual(row['fetched_at'], '2026-10-11T09:00:00+09:00')
        self.assertEqual(row['terms_status'], '未確認')
        self.assertTrue(row['simulator'])
        self.assertIn('自動反映しません', row['notice'])
        self.assertEqual(self.store.price_versions(), [])

    def test_record_and_read_manual_fixture_without_price_changes(self):
        item = demo_item(item_id='m25-price', price_type='仕入', unit_price='80')
        price = self.store.add_price(item, '架空担当')
        payload = dict(m25.SPEC['defaults'])
        payload.update(action='record', source='手入力fixture:架空', series='架空原料指標',
                       terms_status='未確認')

        saved = m25.run(payload, self.store)
        listed = m25.run({'action': 'list'}, self.store)

        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(listed['observations'][0]['source'], '手入力fixture:架空')
        self.assertEqual(len(self.store.price_versions('m25-price')), 1)
        self.assertEqual(self.store.price_versions('m25-price')[0]['price_version_id'],
                         price['price_version_id'])
        self.assertEqual(self.store.get_price('m25-price', '仕入')['item']['unit_price'], '80')

    def test_empty_listing_does_not_seed_and_repeated_demo_seed_is_explicit_append(self):
        self.assertEqual(m25.run({}, self.store)['observations'], [])
        self.assertEqual(self.store.records(m25.NAMESPACE), [])

        m25.run(m25.SPEC['defaults'], self.store)
        m25.run(m25.SPEC['defaults'], self.store)
        self.assertEqual(len(self.store.records(m25.NAMESPACE)), 2)
        self.assertEqual(self.store.price_versions(), [])

    def test_invalid_fields_and_timestamps_are_rejected(self):
        for patch in (
            {'value': 'NaN'}, {'value': '-2'}, {'source': ' '},
            {'published_at': 'yesterday'}, {'fetched_at': '2026-10-11T09:00:00'},
        ):
            payload = dict(m25.SPEC['defaults'])
            payload.update(action='record', **patch)
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                m25.run(payload, self.store)
        with self.assertRaises(ValidationError):
            m25.run({'action': 'list', 'unexpected': True}, self.store)
        with self.assertRaises(ValidationError):
            m25.run({'action': 'unknown'}, self.store)


if __name__ == '__main__':
    unittest.main()
