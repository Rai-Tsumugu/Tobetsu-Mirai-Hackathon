import unittest

from src.auto_repair_items.core import DEMO_DATE, Store, ValidationError, seed_demo
from src.auto_repair_items.m03 import SPEC, run


class M03Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def save_price(self, price_type, amount, *, item_id='paint-1', updated_at=DEMO_DATE):
        return run({
            'action': 'save_price',
            'item': {
                'item_id': item_id,
                'name': '架空塗料',
                'category': '塗料',
                'unit': 'ml',
                'unit_price': amount,
                'price_type': price_type,
                'source': 'simulator:架空値',
                'updated_at': updated_at,
            },
            'confirmed_by': '架空デモ担当',
        }, self.store)

    def test_spec_defaults_run_after_demo_seed(self):
        seed_demo(self.store)

        result = run(SPEC['defaults'], self.store)

        self.assertEqual(result['item']['item_id'], 'demo-paint')
        self.assertEqual(result['item']['price_type'], '販売')
        self.assertEqual(result['item']['unit_price'], '120')
        self.assertEqual(result['status'], 'approved')

    def test_purchase_and_sale_prices_are_independent(self):
        self.save_price('仕入', '80.25')
        sale = self.save_price('販売', '123.40')

        purchase_result = run({
            'item_id': 'paint-1', 'price_type': '仕入', 'as_of': DEMO_DATE,
        }, self.store)
        sale_result = run({
            'item_id': 'paint-1', 'price_type': '販売', 'as_of': DEMO_DATE,
        }, self.store)

        self.assertEqual(purchase_result['item']['unit_price'], '80.25')
        self.assertEqual(sale_result['item']['unit_price'], '123.40')
        self.assertEqual(sale_result['currency'], 'JPY')
        self.assertEqual(sale_result['price_version_id'], sale['price_version_id'])
        self.assertEqual(len(self.store.price_versions('paint-1', '仕入')), 1)
        self.assertEqual(len(self.store.price_versions('paint-1', '販売')), 1)

    def test_sale_update_does_not_change_purchase_or_apply_markup(self):
        self.save_price('仕入', '80')
        self.save_price('販売', '125')
        self.save_price('販売', '130', updated_at='2026-10-12')

        purchase = run({'item_id': 'paint-1', 'price_type': '仕入'}, self.store)
        sale = run({
            'item_id': 'paint-1', 'price_type': '販売', 'as_of': '2026-10-12',
        }, self.store)

        self.assertEqual(purchase['item']['unit_price'], '80')
        self.assertEqual(sale['item']['unit_price'], '130')
        self.assertEqual(sale['item']['price_type'], '販売')

    def test_missing_sale_price_stops_instead_of_using_purchase(self):
        self.save_price('仕入', '80')

        with self.assertRaisesRegex(ValidationError, '価格未確認'):
            run({'item_id': 'paint-1', 'price_type': '販売'}, self.store)

    def test_retrieval_validates_type_unit_and_date(self):
        self.save_price('販売', '123.45')

        with self.assertRaises(ValidationError):
            run({'item_id': 'paint-1', 'price_type': '掛率'}, self.store)
        with self.assertRaisesRegex(ValidationError, '単位不一致'):
            run({'item_id': 'paint-1', 'price_type': '販売', 'unit': '本'}, self.store)
        with self.assertRaisesRegex(ValidationError, '価格未確認'):
            run({'item_id': 'paint-1', 'price_type': '販売', 'as_of': '2026-10-10'}, self.store)

    def test_save_rejects_unconfirmed_or_invalid_price_input(self):
        base = {
            'action': 'save_price',
            'item': {
                'item_id': 'paint-1', 'name': '架空塗料', 'category': '塗料',
                'unit': 'ml', 'unit_price': '1', 'price_type': '販売',
                'source': 'simulator:架空値', 'updated_at': DEMO_DATE,
            },
            'confirmed_by': '架空デモ担当',
        }
        for mutate in (
            lambda payload: payload.pop('confirmed_by'),
            lambda payload: payload['item'].update(unit_price='-1'),
            lambda payload: payload['item'].update(price_type='不明'),
            lambda payload: payload['item'].pop('source'),
            lambda payload: payload.update(valid_until='2026-10-10'),
            lambda payload: payload.update(currency='JP'),
        ):
            payload = {
                **base,
                'item': dict(base['item']),
            }
            mutate(payload)
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                run(payload, self.store)

    def test_unknown_action_and_non_dict_payload_are_rejected(self):
        for payload in (None, [], {'action': 'calculate_markup'}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                run(payload, self.store)


if __name__ == '__main__':
    unittest.main()
