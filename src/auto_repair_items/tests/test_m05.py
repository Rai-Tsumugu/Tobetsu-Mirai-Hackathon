import unittest

from src.auto_repair_items.core import DEMO_DATE, Store, ValidationError, seed_demo
from src.auto_repair_items.m05 import SPEC, run


class M05Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        seed_demo(self.store)

    def tearDown(self):
        self.store.close()

    def save_formula(self, *, formula_id='formula-1', ratio='1', unit='ml', status='approved'):
        return run({
            'action': 'save_formula',
            'formula_id': formula_id,
            'code': 'SIM-BLUE-01',
            'version': 1,
            'status': status,
            'confirmed_by': '架空デモ担当',
            'formula_lines': [{'item_id': 'demo-paint', 'ratio': ratio, 'unit': unit}],
            'base_qty': '100',
            'unit': 'ml',
            'as_of': DEMO_DATE,
        }, self.store)

    def test_spec_defaults_run_after_demo_seed(self):
        result = run(SPEC['defaults'], self.store)

        self.assertEqual(result['formula']['formula_id'], 'demo-metallic-blue')
        self.assertEqual(result['total_cost'], '8000')
        self.assertEqual(result['currency'], 'JPY')
        self.assertTrue(result['simulator'])

    def test_formula_is_saved_and_calculates_from_approved_component_price(self):
        result = self.save_formula()

        saved = self.store.latest('formula', 'formula-1')
        self.assertEqual(saved['formula_lines'], [
            {'item_id': 'demo-paint', 'ratio': '1', 'unit': 'ml'},
        ])
        self.assertEqual(saved['confirmed_by'], '架空デモ担当')
        self.assertEqual(result['lines'][0]['quantity'], '100')
        self.assertEqual(result['lines'][0]['unit_price'], '80')
        self.assertEqual(result['total_cost'], '8000')

    def test_multiple_lines_use_exact_decimal_ratios_and_prices(self):
        self.store.add_price({
            'item_id': 'demo-solvent', 'name': '架空溶剤', 'category': '溶剤',
            'unit': 'ml', 'unit_price': '0.15', 'price_type': '仕入',
            'source': 'simulator:架空値', 'updated_at': DEMO_DATE,
        }, '架空デモ担当')
        run({
            'action': 'save_formula', 'formula_id': 'formula-2', 'code': 'SIM-02',
            'version': 1, 'status': 'approved', 'confirmed_by': '架空デモ担当',
            'formula_lines': [
                {'item_id': 'demo-paint', 'ratio': '0.75', 'unit': 'ml'},
                {'item_id': 'demo-solvent', 'ratio': '0.25', 'unit': 'ml'},
            ],
            'base_qty': '10.4', 'unit': 'ml', 'as_of': DEMO_DATE,
        }, self.store)

        result = run({
            'action': 'calculate', 'formula_id': 'formula-2',
            'base_qty': '10.4', 'unit': 'ml', 'as_of': DEMO_DATE,
        }, self.store)
        self.assertEqual(result['lines'][0]['quantity'], '7.800')
        self.assertEqual(result['lines'][1]['quantity'], '2.600')
        self.assertEqual(result['total_cost'], '624.39000')

    def test_unapproved_formula_can_be_saved_but_cannot_be_retrieved_or_calculated(self):
        self.save_formula(status='pending')

        for action in ('get_formula', 'calculate'):
            with self.subTest(action=action), self.assertRaisesRegex(ValidationError, '未承認配合'):
                run({
                    'action': action, 'formula_id': 'formula-1',
                    'base_qty': '100', 'unit': 'ml',
                }, self.store)

        approved = run({
            'action': 'approve_formula', 'formula_id': 'formula-1',
            'confirmed_by': '架空承認者',
        }, self.store)
        self.assertEqual(approved['formula']['status'], 'approved')
        result = run({
            'action': 'calculate', 'formula_id': 'formula-1',
            'base_qty': '100', 'unit': 'ml',
        }, self.store)
        self.assertEqual(result['total_cost'], '8000')
        self.assertEqual(len(self.store.records('formula', 'formula-1')), 2)

    def test_inconsistent_ratio_and_units_stop_without_saving(self):
        with self.assertRaisesRegex(ValidationError, '比率の合計'):
            self.save_formula(ratio='0.9')
        with self.assertRaisesRegex(ValidationError, '単位不一致'):
            self.save_formula(unit='g')
        self.assertEqual(self.store.records('formula', 'formula-1'), [])

    def test_bad_lines_versions_and_missing_price_stop(self):
        for formula_lines in (
            [],
            [{'item_id': 'demo-paint', 'ratio': '0', 'unit': 'ml'}],
            [{'item_id': 'demo-paint', 'ratio': '1.1', 'unit': 'ml'}],
            [{'item_id': 'demo-paint', 'ratio': '0.5', 'unit': 'ml'},
             {'item_id': 'demo-paint', 'ratio': '0.5', 'unit': 'ml'}],
        ):
            with self.subTest(formula_lines=formula_lines), self.assertRaises(ValidationError):
                run({
                    'action': 'save_formula', 'formula_id': 'invalid', 'code': 'SIM',
                    'version': 1, 'confirmed_by': '架空デモ担当',
                    'formula_lines': formula_lines, 'base_qty': '1', 'unit': 'ml',
                }, self.store)

        self.save_formula()
        with self.assertRaisesRegex(ValidationError, '指定した版'):
            run({'action': 'get_formula', 'formula_id': 'formula-1', 'version': 2}, self.store)
        with self.assertRaisesRegex(ValidationError, '価格未確認'):
            run({
                'action': 'save_formula', 'formula_id': 'missing-price', 'code': 'SIM',
                'version': 1, 'status': 'approved', 'confirmed_by': '架空デモ担当',
                'formula_lines': [{'item_id': 'absent-item', 'ratio': '1', 'unit': 'ml'}],
                'base_qty': '1', 'unit': 'ml', 'as_of': DEMO_DATE,
            }, self.store)
        self.assertEqual(self.store.records('formula', 'missing-price'), [])

    def test_rejects_bad_action_and_non_dict_payload(self):
        for payload in (None, [], {'action': 'remove_formula'}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                run(payload, self.store)


if __name__ == '__main__':
    unittest.main()
