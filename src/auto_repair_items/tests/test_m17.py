"""M17 candidate comparison and human decision tests."""

import unittest

from auto_repair_items import m17
from auto_repair_items.core import Store, ValidationError, demo_item


class M17Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def candidate(self, *, price='88', unit='ml', price_type='仕入', supplier='supplier-a',
                  conditions='月末締め翌月末払い', name='架空サンプル塗料'):
        item = demo_item('m17-paint', price_type, price, unit)
        item['name'] = name
        return {'item': item, 'supplier_id': supplier,
                'transaction_conditions': conditions, 'valid_from': '2026-10-11',
                'simulator': True}

    def add_old(self, *, price='80', unit='ml', price_type='仕入', supplier='supplier-a',
                conditions='月末締め翌月末払い', name='架空サンプル塗料'):
        item = demo_item('m17-paint', price_type, price, unit)
        item['name'] = name
        return self.store.add_price(item, '旧価格確認者', supplier_id=supplier,
                                    transaction_conditions=conditions, currency='JPY',
                                    reason='旧価格確認')

    def test_defaults_seed_fictional_old_price_and_compare_candidate(self):
        result = m17.run(m17.SPEC['defaults'], self.store)

        self.assertTrue(result['comparison']['comparable'])
        self.assertEqual(result['comparison']['old_unit_price'], '80')
        self.assertEqual(result['comparison']['candidate_unit_price'], '88')
        self.assertEqual(result['comparison']['difference'], '8')
        self.assertEqual(result['comparison']['difference_rate_percent'], '10.0')
        self.assertTrue(result['comparison']['simulator'])
        self.assertEqual(len(self.store.records('m17_update_reviews')), 1)

    def test_conditions_must_match_before_showing_a_price_difference(self):
        cases = (
            ('unit', {'unit': '個'}),
            ('price_type', {'price_type': '販売'}),
            ('supplier_id', {'supplier': 'supplier-b'}),
            ('transaction_conditions', {'conditions': '現金払い'}),
            ('name', {'name': '別品目'}),
        )
        for key, change in cases:
            with self.subTest(key=key):
                self.add_old()
                result = m17.run({'item_id': 'm17-paint', 'candidate': self.candidate(**change)}, self.store)
                self.assertFalse(result['comparison']['comparable'])
                self.assertIsNone(result['comparison']['difference'])
                self.assertIsNone(result['comparison']['difference_rate_percent'])
                self.store.close()
                self.store = Store()

    def test_adoption_records_reviewer_reason_and_new_approved_price_version(self):
        original = self.add_old()
        result = m17.run({
            'item_id': 'm17-paint', 'candidate': self.candidate(), 'decision': '採用',
            'confirmed_by': '担当A', 'reason': '仕入先の新価格表を確認',
        }, self.store)

        versions = self.store.price_versions('m17-paint', '仕入', 'supplier-a')
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]['price_version_id'], original['price_version_id'])
        self.assertEqual(versions[1]['item']['unit_price'], '88')
        self.assertEqual(versions[1]['status'], 'approved')
        self.assertEqual(versions[1]['confirmed_by'], '担当A')
        self.assertEqual(versions[1]['reason'], '仕入先の新価格表を確認')
        review = self.store.records('m17_update_reviews')[0]
        self.assertEqual(review['decision'], '採用')
        self.assertEqual(review['reviewer'], '担当A')
        self.assertEqual(review['reason'], '仕入先の新価格表を確認')
        self.assertEqual(result['price_version_id'], versions[1]['price_version_id'])

    def test_hold_is_appended_without_changing_the_price(self):
        original = self.add_old()
        result = m17.run({'item_id': 'm17-paint', 'candidate': self.candidate(),
                          'decision': '保留', 'confirmed_by': '担当B', 'reason': '再確認待ち'}, self.store)

        self.assertEqual(result['decision'], '保留')
        self.assertEqual(len(self.store.price_versions('m17-paint')), 1)
        self.assertEqual(self.store.price_versions('m17-paint')[0]['price_version_id'], original['price_version_id'])
        self.assertEqual(self.store.records('m17_update_reviews')[0]['reason'], '再確認待ち')

    def test_incompatible_candidate_cannot_be_adopted(self):
        self.add_old()
        with self.assertRaisesRegex(ValidationError, '比較不可'):
            m17.run({'item_id': 'm17-paint', 'candidate': self.candidate(supplier='other'),
                     'decision': '採用', 'confirmed_by': '担当', 'reason': '条件不一致'}, self.store)
        self.assertEqual(len(self.store.price_versions('m17-paint')), 1)
        self.assertEqual(len(self.store.records('m17_update_reviews')), 0)

    def test_required_confirmation_reason_and_candidate_fields_are_validated(self):
        self.add_old()
        base = {'item_id': 'm17-paint', 'candidate': self.candidate(), 'decision': '採用',
                'confirmed_by': '担当', 'reason': '確認'}
        for field in ('confirmed_by', 'reason'):
            payload = dict(base)
            del payload[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                m17.run(payload, self.store)
        candidate = self.candidate()
        del candidate['transaction_conditions']
        with self.assertRaises(ValidationError):
            m17.run({'item_id': 'm17-paint', 'candidate': candidate}, self.store)


if __name__ == '__main__':
    unittest.main()
