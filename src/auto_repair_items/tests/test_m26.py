"""M26 gross margin impact simulation tests."""

import unittest

from auto_repair_items import m26
from auto_repair_items.core import Store, ValidationError, demo_item, seed_demo


class M26Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_explicit_demo_seeds_four_prices_and_records_decimal_simulation(self):
        result = m26.run(m26.SPEC['defaults'], self.store)
        simulation = result['simulation']
        self.assertEqual(simulation['prices'], {
            'old_purchase': '70', 'old_sales': '105', 'new_purchase': '80', 'new_sales': '120',
        })
        self.assertEqual(simulation['quantity'], '10')
        self.assertEqual(simulation['old_gross_margin'], '350')
        self.assertEqual(simulation['new_gross_margin'], '400')
        self.assertEqual(simulation['gross_margin_change'], '50')
        self.assertTrue(result['simulation_only'])
        self.assertTrue(result['simulator'])
        self.assertIn('人件費・税・廃棄', result['notice'])
        self.assertEqual(len(self.store.price_versions('demo-paint')), 4)
        self.assertEqual(len(self.store.records(m26.NAMESPACE)), 1)

    def test_demo_reuses_explicit_shared_core_seed_prices(self):
        seed_demo(self.store)
        result = m26.run(m26.SPEC['defaults'], self.store)
        self.assertEqual(result['simulation']['prices']['new_purchase'], '80')
        self.assertEqual(result['simulation']['prices']['new_sales'], '120')
        self.assertEqual(len(self.store.price_versions('demo-paint')), 4)

    def test_simulate_reads_explicit_price_versions_without_changing_them(self):
        ids = {}
        for role, price_type, amount in (
            ('old_purchase', '仕入', '10.25'), ('old_sales', '販売', '16.5'),
            ('new_purchase', '仕入', '12'), ('new_sales', '販売', '19.75'),
        ):
            item = demo_item(item_id='paint-x', price_type=price_type, unit_price=amount)
            version = self.store.add_price(item, '担当者', transaction_conditions={'freight_basis': 'included'})
            ids[role] = version['price_version_id']
        before = self.store.price_versions('paint-x')
        result = m26.run({
            'action': 'simulate', 'item_id': 'paint-x', 'unit': 'ml', 'quantity': '2.5',
            'transaction_conditions': {'freight_basis': 'included'},
            'confirmed_by': '担当者', **ids,
        }, self.store)
        row = result['simulation']
        self.assertEqual(row['old_gross_margin'], '15.625')
        self.assertEqual(row['new_gross_margin'], '19.375')
        self.assertEqual(row['gross_margin_change'], '3.750')
        self.assertEqual(self.store.price_versions('paint-x'), before)
        self.assertEqual(len(self.store.records(m26.NAMESPACE)), 1)

    def test_mismatched_item_unit_type_conditions_or_missing_side_stops(self):
        ids = {}
        for role, price_type, amount in (
            ('old_purchase', '仕入', '10'), ('old_sales', '販売', '15'),
            ('new_purchase', '仕入', '11'), ('new_sales', '販売', '17'),
        ):
            item = demo_item(item_id='paint-x', price_type=price_type, unit_price=amount)
            version = self.store.add_price(item, '担当者', transaction_conditions={'freight_basis': 'included'})
            ids[role] = version['price_version_id']
        base = {'action': 'simulate', 'item_id': 'paint-x', 'unit': 'ml', 'quantity': '1',
                'transaction_conditions': {'freight_basis': 'included'}, 'confirmed_by': '担当者', **ids}
        for patch, message in (
            ({'unit': 'g'}, '単位'),
            ({'transaction_conditions': {}}, '取引条件'),
            ({'old_sales': ids['old_purchase']}, '価格区分'),
            ({'new_purchase': 'missing'}, '指定価格版'),
        ):
            with self.subTest(patch=patch), self.assertRaisesRegex(ValidationError, message):
                m26.run(base | patch, self.store)
        self.assertEqual(self.store.records(m26.NAMESPACE), [])

    def test_invalid_quantity_unknown_action_and_list_do_not_implicitly_seed(self):
        self.assertEqual(m26.run({'action': 'list'}, self.store)['simulations'], [])
        self.assertEqual(self.store.price_versions(), [])
        for quantity in ('0', '-1', 'NaN'):
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                m26.run(m26.SPEC['defaults'] | {'quantity': quantity}, self.store)
        with self.assertRaises(ValidationError):
            m26.run({'action': 'surprise'}, self.store)
        with self.assertRaises(ValidationError):
            m26.run(m26.SPEC['defaults'] | {'unexpected': True}, self.store)


if __name__ == '__main__':
    unittest.main()
