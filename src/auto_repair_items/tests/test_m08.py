import unittest

from auto_repair_items.core import DEMO_DATE, Store, ValidationError, demo_item, seed_demo
from auto_repair_items.m08 import SPEC, run


class M08Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        seed_demo(self.store)

    def tearDown(self):
        self.store.close()

    def payload(self, **changes):
        result = dict(SPEC['defaults'])
        result.update(changes)
        return result

    def add_supplier_price(self, supplier_id, price, *, price_type='仕入'):
        return self.store.add_price(
            demo_item(item_id='demo-paint', price_type=price_type, unit_price=price),
            '架空デモ担当', supplier_id=supplier_id,
        )

    def test_defaults_preview_against_seeded_demo_without_saving(self):
        before = self.store.price_versions('demo-paint', '販売')

        result = run(SPEC['defaults'], self.store)

        self.assertEqual(result['status'], 'preview')
        self.assertEqual(result['current_price'], '120')
        self.assertEqual(result['new_price'], '130')
        self.assertEqual(result['difference'], '10')
        self.assertEqual(result['direction'], 'increase')
        self.assertTrue(result['requires_confirmation'])
        self.assertNotIn('_values', result)
        self.assertEqual(self.store.price_versions('demo-paint', '販売'), before)

    def test_search_matches_name_or_id_and_keeps_price_types_separate(self):
        self.add_supplier_price('supplier-a', '80', price_type='仕入')

        result = run({'action': 'search_items', 'query': '架空サンプル'}, self.store)

        self.assertEqual({candidate['price_type'] for candidate in result['candidates']}, {'仕入', '販売'})
        self.assertTrue(all(candidate['item']['item_id'] == 'demo-paint' for candidate in result['candidates']))
        filtered = run({
            'action': 'search_items', 'query': 'DEMO-PAINT', 'price_type': '仕入',
        }, self.store)
        self.assertEqual(len(filtered['candidates']), 2)
        self.assertTrue(all(candidate['item']['price_type'] == '仕入'
                            for candidate in filtered['candidates']))

    def test_confirm_appends_version_and_preserves_old_price_and_other_price_type(self):
        purchase = self.add_supplier_price('supplier-a', '80', price_type='仕入')
        preview = run(self.payload(), self.store)
        result = run(self.payload(
            action='confirm_change',
            expected_price_version_id=preview['current_price_version_id'],
        ), self.store)

        self.assertEqual(result['status'], 'saved')
        self.assertEqual(result['item']['unit_price'], '130')
        self.assertEqual(result['item']['source'], self.payload()['source'])
        self.assertEqual(result['confirmed_by'], '架空デモ担当')
        self.assertEqual(result['price_version_id'], self.store.price_versions('demo-paint', '販売')[-1]['price_version_id'])
        self.assertEqual(result['previous_price_version_id'], preview['current_price_version_id'])
        self.assertEqual(len(self.store.price_versions('demo-paint', '販売')), 2)
        self.assertEqual(self.store.price_versions('demo-paint', '販売')[0]['item']['unit_price'], '120')
        self.assertEqual(self.store.price_versions('demo-paint', '販売')[-1]['reason'], '架空デモ価格の見直し')
        self.assertEqual(self.store.price_versions('demo-paint', '販売')[-1]['metadata']['checked_at'], DEMO_DATE)
        self.assertEqual(self.store.price_versions('demo-paint', '仕入')[-1]['price_version_id'], purchase['price_version_id'])

    def test_purchase_price_change_requires_supplier_when_ambiguous_and_updates_only_selected_supplier(self):
        self.add_supplier_price('supplier-a', '80')
        self.add_supplier_price('supplier-b', '90')
        with self.assertRaisesRegex(ValidationError, '仕入先の選択'):
            run(self.payload(price_type='仕入', new_price='85'), self.store)

        changes = self.payload(price_type='仕入', new_price='85', supplier_id='supplier-a')
        preview = run(changes, self.store)
        saved = run({
            **changes, 'action': 'confirm_change',
            'expected_price_version_id': preview['current_price_version_id'],
        }, self.store)
        self.assertEqual(saved['supplier_id'], 'supplier-a')
        self.assertEqual(saved['item']['price_type'], '仕入')
        self.assertEqual(saved['item']['unit_price'], '85')
        self.assertEqual(len(self.store.price_versions('demo-paint', '仕入', 'supplier-b')), 1)

    def test_stale_preview_and_missing_confirmation_do_not_save(self):
        preview = run(self.payload(), self.store)
        self.store.add_price(
            demo_item(item_id='demo-paint', price_type='販売', unit_price='70'),
            '架空デモ担当',
        )
        with self.assertRaisesRegex(ValidationError, 'プレビュー後に変更'):
            run(self.payload(
                action='confirm_change',
                expected_price_version_id=preview['current_price_version_id'],
            ), self.store)
        with self.assertRaises(ValidationError):
            run(self.payload(action='confirm_change'), self.store)
        self.assertEqual(len(self.store.price_versions('demo-paint', '販売')), 2)

    def test_validation_requires_a_real_positive_price_and_all_change_evidence(self):
        for changes in (
            {'item_id': 'missing-item'},
            {'price_type': '不明'},
            {'new_price': '0'},
            {'new_price': '-1'},
            {'new_price': 'NaN'},
            {'reason': ' '},
            {'source': ''},
            {'checked_at': 'yesterday'},
            {'confirmed_by': None},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                run(self.payload(**changes), self.store)
        self.assertEqual(len(self.store.price_versions('demo-paint', '販売')), 1)

    def test_same_price_is_recorded_as_unchanged_and_date_cannot_rewrite_history(self):
        same = run(self.payload(new_price='120'), self.store)
        self.assertEqual(same['direction'], 'unchanged')
        with self.assertRaisesRegex(ValidationError, '開始日以降'):
            run(self.payload(checked_at='2026-10-10'), self.store)

    def test_rejects_bad_action_payload_and_empty_search(self):
        for payload in (None, [], {'action': 'delete'}, {'action': 'search_items', 'query': ' '}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                run(payload, self.store)


if __name__ == '__main__':
    unittest.main()
