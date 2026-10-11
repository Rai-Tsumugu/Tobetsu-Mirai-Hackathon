import unittest

from auto_repair_items.core import DEMO_DATE, Store, ValidationError, demo_item, seed_demo
from auto_repair_items.m04 import SPEC, run


class M04Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        seed_demo(self.store)

    def tearDown(self):
        self.store.close()

    def save_offer(self, initial_supplier_id, price, **changes):
        payload = {
            'action': 'save_offer',
            'item': demo_item(item_id='demo-paint', price_type='仕入', unit_price=price),
            'supplier_id': initial_supplier_id,
            'freight_basis': '送料込み',
            'freight_amount': '0',
            'tax_basis': '税別',
            'delivery_days': 2,
            'checked_at': DEMO_DATE,
            'confirmed_by': '架空デモ担当',
        }
        payload.update(changes)
        return run(payload, self.store)

    def compare(self, suppliers, selected_supplier_id, **changes):
        payload = {
            'action': 'compare_and_select',
            'item_id': 'demo-paint',
            'unit': 'ml',
            'supplier_ids': suppliers,
            'selected_supplier_id': selected_supplier_id,
            'confirmed_by': '架空デモ担当',
            'as_of': DEMO_DATE,
        }
        payload.update(changes)
        return run(payload, self.store)

    def test_defaults_save_a_demo_supplier_offer_after_demo_seed(self):
        result = run(SPEC['defaults'], self.store)

        self.assertEqual(result['item']['item_id'], 'demo-paint')
        self.assertEqual(result['item']['price_type'], '仕入')
        self.assertEqual(result['supplier_id'], 'demo-supplier-a')
        self.assertEqual(result['freight_basis'], '送料込み')
        self.assertEqual(result['status'], 'approved')

    def test_comparison_ranks_same_terms_and_persists_the_human_selection(self):
        low = self.save_offer('supplier-a', '78.25')
        high = self.save_offer('supplier-b', '82.50')

        result = self.compare(['supplier-b', 'supplier-a'], 'supplier-b')

        self.assertEqual(result['ranked_supplier_ids'], ['supplier-a', 'supplier-b'])
        self.assertEqual(result['selected']['price_version_id'], high['price_version_id'])
        self.assertEqual(result['selected']['item']['unit_price'], '82.50')
        self.assertEqual(result['selected']['price_version_id'], high['price_version_id'])
        saved = self.store.latest('supplier_price_selection', result['selection_record_id'])
        self.assertEqual(saved['supplier_id'], 'supplier-b')
        self.assertEqual(saved['price_version_id'], high['price_version_id'])
        self.assertEqual(saved['conditions']['delivery_days'], 2)
        self.assertNotEqual(low['price_version_id'], high['price_version_id'])

    def test_comparison_refuses_different_freight_tax_or_delivery_terms(self):
        self.save_offer('supplier-a', '78')
        self.save_offer('supplier-b', '82', freight_basis='送料別')

        with self.assertRaisesRegex(ValidationError, '比較条件不一致'):
            self.compare(['supplier-a', 'supplier-b'], 'supplier-a')
        self.assertEqual(self.store.records('supplier_price_selection'), [])

        self.store.close()
        self.store = Store()
        seed_demo(self.store)
        self.save_offer('supplier-a', '78')
        self.save_offer('supplier-b', '82', tax_basis='税込')
        with self.assertRaisesRegex(ValidationError, '比較条件不一致'):
            self.compare(['supplier-a', 'supplier-b'], 'supplier-a')

        self.store.close()
        self.store = Store()
        seed_demo(self.store)
        self.save_offer('supplier-a', '78')
        self.save_offer('supplier-b', '82', delivery_days=3)
        with self.assertRaisesRegex(ValidationError, '比較条件不一致'):
            self.compare(['supplier-a', 'supplier-b'], 'supplier-a')

    def test_other_item_unit_and_currency_cannot_be_mixed(self):
        self.save_offer('supplier-a', '78')
        self.save_offer('supplier-b', '82', item=demo_item(item_id='other-paint', price_type='仕入'))
        with self.assertRaises(ValidationError):
            self.compare(['supplier-a', 'supplier-b'], 'supplier-a')

        self.save_offer('supplier-c', '75', currency='USD')
        with self.assertRaisesRegex(ValidationError, '比較条件不一致'):
            self.compare(['supplier-a', 'supplier-c'], 'supplier-a')

        with self.assertRaisesRegex(ValidationError, '単位不一致'):
            self.compare(['supplier-a'], 'supplier-a', unit='本')

    def test_only_purchase_prices_and_confirmed_offers_can_be_compared(self):
        sale_item = demo_item(item_id='sale-item', price_type='販売', unit_price='120')
        with self.assertRaisesRegex(ValidationError, '仕入価格のみ登録'):
            run({**SPEC['defaults'], 'item': sale_item}, self.store)

        self.save_offer('pending-supplier', '90', status='pending')
        with self.assertRaisesRegex(ValidationError, '価格未確認'):
            self.compare(['pending-supplier'], 'pending-supplier')

    def test_validation_rejects_missing_terms_bad_delivery_and_unlisted_selection(self):
        for changes in (
            {'supplier_id': ''},
            {'freight_basis': ' '},
            {'tax_basis': None},
            {'freight_amount': '-1'},
            {'delivery_days': '1.5'},
            {'checked_at': 'unknown'},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.save_offer('supplier-a', '80', **changes)

        self.save_offer('supplier-a', '80')
        with self.assertRaisesRegex(ValidationError, '比較候補から'):
            self.compare(['supplier-a'], 'supplier-b')
        with self.assertRaisesRegex(ValidationError, '重複'):
            self.compare(['supplier-a', 'supplier-a'], 'supplier-a')
        with self.assertRaises(ValidationError):
            run({'action': 'save_price'}, self.store)


if __name__ == '__main__':
    unittest.main()
