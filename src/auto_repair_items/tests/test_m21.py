import unittest

from auto_repair_items.core import DEMO_DATE, Store, ValidationError, demo_item, seed_demo
from auto_repair_items.m21 import SPEC, run


class M21Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        seed_demo(self.store)

    def tearDown(self):
        self.store.close()

    def register(self, **overrides):
        payload = dict(SPEC['defaults'])
        payload.update(overrides)
        return run(payload, self.store)

    def test_explicit_demo_formula_then_calculation_snapshot_and_approval(self):
        formula = self.register()['formula']
        self.assertEqual(formula['formula_id'], 'demo-m21-blue')
        result = run({
            'action': 'calculate', 'formula_id': formula['formula_id'],
            'version': 1, 'total_qty': '12.50', 'unit': 'ml', 'as_of': DEMO_DATE,
        }, self.store)
        snapshot = result['snapshot']
        self.assertEqual(snapshot['status'], 'needs_human_confirmation')
        self.assertEqual(snapshot['lines'][0]['quantity'], '12.50')
        self.assertEqual(snapshot['lines'][0]['price_version_id'], self.store.price_versions('demo-paint')[0]['price_version_id'])
        self.assertEqual(snapshot['total_cost'], '1000.00')

        approved = run({
            'action': 'approve_snapshot', 'snapshot_id': snapshot['snapshot_id'],
            'confirmed_by': '工場担当',
        }, self.store)['snapshot']
        self.assertEqual(approved['status'], 'approved')
        self.assertEqual(approved['confirmed_by'], '工場担当')
        saved = run({'action': 'get_snapshot', 'snapshot_id': snapshot['snapshot_id']}, self.store)
        self.assertEqual(saved['snapshot']['lines'][0]['quantity'], '12.50')

    def test_ratio_total_and_units_are_validated(self):
        with self.assertRaisesRegex(ValidationError, '配合比率'):
            self.register(formula_lines=[{'item_id': 'demo-paint', 'ratio': '0.5', 'unit': 'ml'}])
        self.register()
        with self.assertRaisesRegex(ValidationError, '単位不一致'):
            run({'action': 'calculate', 'formula_id': 'demo-m21-blue', 'total_qty': '3', 'unit': 'g'}, self.store)

    def test_pending_formula_and_unconfirmed_price_stop_calculation(self):
        self.register(status='pending')
        with self.assertRaisesRegex(ValidationError, '未承認配合'):
            run({'action': 'calculate', 'formula_id': 'demo-m21-blue', 'total_qty': '3', 'unit': 'ml'}, self.store)

        run({**SPEC['defaults'], 'formula_id': 'no-price-formula',
             'formula_lines': [{'item_id': 'missing-item', 'ratio': '1', 'unit': 'ml'}]}, self.store)
        with self.assertRaisesRegex(ValidationError, '価格未確認'):
            run({'action': 'calculate', 'formula_id': 'no-price-formula', 'total_qty': '3', 'unit': 'ml'}, self.store)

    def test_zero_price_is_not_treated_as_a_confirmed_cost(self):
        self.store.add_price(demo_item(item_id='zero-paint', price_type='仕入', unit_price='0'), '架空デモ担当')
        self.register(formula_id='zero-formula', formula_lines=[
            {'item_id': 'zero-paint', 'ratio': '1', 'unit': 'ml'},
        ])
        with self.assertRaisesRegex(ValidationError, '0円'):
            run({'action': 'calculate', 'formula_id': 'zero-formula', 'total_qty': '1', 'unit': 'ml'}, self.store)


if __name__ == '__main__':
    unittest.main()
