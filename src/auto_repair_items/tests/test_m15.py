"""M15 price-version validity tests."""

import unittest

from auto_repair_items import m15
from auto_repair_items.core import Store, ValidationError, demo_item


class M15Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_defaults_seed_a_fictional_price_and_distinguish_no_expiry(self):
        result = m15.run(m15.SPEC['defaults'], self.store)

        self.assertEqual(result['price_versions'][0]['status'], '期限なし')
        self.assertTrue(result['simulator'])
        self.assertEqual(len(self.store.price_versions('demo-m15-paint', '仕入')), 1)

    def test_pending_price_is_reported_unconfirmed(self):
        item = demo_item('m15-pending', '仕入', '500')
        self.store.add_price(item, '架空確認者', status='pending', valid_until='2026-10-15')

        result = m15.run({'item_id': 'm15-pending', 'as_of': '2026-10-11'}, self.store)

        self.assertEqual(result['price_versions'][0]['status'], '未確認')

    def test_set_validity_appends_a_version_with_reason_and_human_confirmation(self):
        item = demo_item('m15-versioned', '仕入', '731')
        original = self.store.add_price(item, '初回担当', valid_from='2026-10-01',
                                        valid_until=None, reason='初回価格')

        result = m15.run({
            'action': 'set_validity', 'item_id': 'm15-versioned', 'price_type': '仕入',
            'valid_from': '2026-10-01', 'valid_until': '2026-10-20',
            'reason': '仕入先の回答に基づき期限を設定', 'confirmed_by': '担当A',
        }, self.store)

        versions = self.store.price_versions('m15-versioned', '仕入')
        self.assertEqual(len(versions), 2)
        self.assertIsNone(versions[0]['valid_until'])
        self.assertEqual(versions[0]['price_version_id'], original['price_version_id'])
        self.assertEqual(versions[1]['item']['unit_price'], '731')
        self.assertEqual(versions[1]['confirmed_by'], '担当A')
        self.assertEqual(versions[1]['reason'], '仕入先の回答に基づき期限を設定')
        self.assertEqual(result['price_status'], '有効')

    def test_expired_version_is_visible_and_cannot_be_used_for_quote(self):
        self.store.add_price(demo_item('m15-expired', '仕入', '450'), '架空担当',
                             valid_from='2026-10-01', valid_until='2026-10-10')

        result = m15.run({'item_id': 'm15-expired', 'as_of': '2026-10-11'}, self.store)

        self.assertEqual(result['price_versions'][0]['status'], '期限切れ')
        with self.assertRaisesRegex(ValidationError, '期限切れ'):
            self.store.get_price('m15-expired', '仕入', as_of='2026-10-11')

    def test_unconfirmed_prices_cannot_be_promoted_by_validity_edit(self):
        self.store.add_price(demo_item('m15-pending-edit', '仕入', '450'), '架空担当',
                             status='pending')
        with self.assertRaisesRegex(ValidationError, '承認済み'):
            m15.run({'action': 'set_validity', 'item_id': 'm15-pending-edit',
                     'reason': '確認', 'confirmed_by': '担当A'}, self.store)

    def test_validation_rejects_missing_confirmation_reason_and_invalid_period(self):
        self.store.add_price(demo_item('m15-invalid', '仕入', '450'), '架空担当')
        common = {'action': 'set_validity', 'item_id': 'm15-invalid'}
        for missing in ('reason', 'confirmed_by'):
            payload = {**common, 'reason': '期限設定', 'confirmed_by': '担当A'}
            payload.pop(missing)
            with self.subTest(missing=missing), self.assertRaises(ValidationError):
                m15.run(payload, self.store)
        with self.assertRaisesRegex(ValidationError, '開始日より前'):
            m15.run({**common, 'valid_from': '2026-10-12', 'valid_until': '2026-10-11',
                     'reason': '誤入力テスト', 'confirmed_by': '担当A'}, self.store)


if __name__ == '__main__':
    unittest.main()
