import unittest
from decimal import Decimal

from auto_repair_items.core import DEMO_DATE, Store, ValidationError, demo_item, seed_demo
from auto_repair_items import m02


class M02Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        seed_demo(self.store)

    def tearDown(self):
        self.store.close()

    def payload(self, **changes):
        result = dict(m02.SPEC['defaults'])
        result.update(changes)
        return result

    def add_packaged_item(self, *, unit='箱', price='100', item_id='demo-bolts'):
        self.store.add_price(
            demo_item(item_id=item_id, price_type='仕入', unit_price=price, unit=unit),
            '架空デモ担当',
        )

    def test_spec_defaults_run_against_demo_seed(self):
        result = m02.run(m02.SPEC['defaults'], self.store)
        self.assertEqual(result['item']['item_id'], 'demo-paint')
        self.assertEqual(result['unit'], 'ml')
        self.assertEqual(result['unit_price'], '80')
        self.assertEqual(result['quantity'], '1')

    def test_box_price_and_quantity_normalize_to_piece(self):
        self.add_packaged_item()
        result = m02.run(self.payload(
            item_id='demo-bolts', source_unit='箱', base_unit='本', factor='4',
            evidence='simulator:架空値、納品書で1箱4本と確認', quantity='2',
        ), self.store)
        self.assertEqual(result['quantity'], '8')
        self.assertEqual(result['unit'], '本')
        self.assertEqual(result['unit_price'], '25')
        self.assertEqual(result['items'][0]['unit'], '本')
        self.assertEqual(result['items'][0]['unit_price'], '25')

    def test_decimal_factor_and_price_are_exact(self):
        self.add_packaged_item(unit='kg', price='12.5', item_id='demo-powder')
        result = m02.run(self.payload(
            item_id='demo-powder', source_unit='kg', base_unit='g', factor='1000',
            evidence='simulator:架空値、1kg=1000g', quantity='0.25',
        ), self.store)
        self.assertEqual(Decimal(result['quantity']), Decimal('250'))
        self.assertEqual(Decimal(result['unit_price']), Decimal('0.0125'))

    def test_repeating_normalized_price_is_rejected_without_rounding(self):
        self.add_packaged_item(price='100', item_id='demo-three')
        payload = self.payload(
            item_id='demo-three', source_unit='箱', base_unit='本', factor='3',
            evidence='simulator:架空値、1箱3本',
        )
        with self.assertRaisesRegex(ValidationError, '丸め規則'):
            m02.run(payload, self.store)
        self.assertEqual(self.store.records('unit_conversion', 'demo-three|箱|本'), [])

    def test_zero_negative_and_non_finite_factor_are_rejected(self):
        self.add_packaged_item()
        for factor in ('0', '-1', 'NaN', 'Infinity'):
            with self.subTest(factor=factor), self.assertRaises(ValidationError):
                m02.run(self.payload(
                    item_id='demo-bolts', source_unit='箱', base_unit='本', factor=factor,
                    evidence='simulator:架空値',
                ), self.store)

    def test_negative_quantity_is_rejected(self):
        self.add_packaged_item()
        with self.assertRaises(ValidationError):
            m02.run(self.payload(
                item_id='demo-bolts', source_unit='箱', base_unit='本', factor='4',
                evidence='simulator:架空値', quantity='-1',
            ), self.store)

    def test_cross_dimension_conversion_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, '次元'):
            m02.run(self.payload(source_unit='L', base_unit='kg', factor='1'), self.store)

    def test_same_unit_requires_identity_factor(self):
        with self.assertRaisesRegex(ValidationError, '同一単位'):
            m02.run(self.payload(factor='2'), self.store)

    def test_unknown_units_and_missing_evidence_are_rejected(self):
        cases = (
            {'source_unit': 'cup', 'base_unit': 'ml'},
            {'evidence': '  '},
            {'factor': None},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                m02.run(self.payload(**changes), self.store)

    def test_package_price_unit_must_match_source_unit(self):
        with self.assertRaisesRegex(ValidationError, '単位不一致'):
            m02.run(self.payload(source_unit='L', base_unit='ml', factor='1000'), self.store)

    def test_unapproved_or_missing_price_is_rejected(self):
        self.store.add_price(
            demo_item(item_id='pending-box', price_type='仕入', unit='箱'),
            '架空デモ担当', status='pending',
        )
        for item_id in ('missing-item', 'pending-box'):
            with self.subTest(item_id=item_id), self.assertRaises(ValidationError):
                m02.run(self.payload(
                    item_id=item_id, source_unit='箱', base_unit='本', factor='4',
                    evidence='simulator:架空値',
                ), self.store)

    def test_changed_conversion_terms_are_not_silently_overwritten(self):
        self.add_packaged_item()
        payload = self.payload(
            item_id='demo-bolts', source_unit='箱', base_unit='本', factor='4',
            evidence='simulator:架空値、1箱4本',
        )
        m02.run(payload, self.store)
        with self.assertRaisesRegex(ValidationError, '登録済み内容'):
            m02.run(dict(payload, factor='5'), self.store)

    def test_conversion_evidence_and_factor_round_trip_in_sqlite(self):
        self.add_packaged_item()
        payload = self.payload(
            item_id='demo-bolts', source_unit='箱', base_unit='本', factor='4.00',
            evidence='simulator:架空値、1箱4本',
        )
        m02.run(payload, self.store)
        record_id = 'demo-bolts|箱|本'
        stored = self.store.latest('unit_conversion', record_id)
        self.assertEqual(stored['factor'], '4.00')
        self.assertEqual(stored['evidence'], payload['evidence'])
        self.assertEqual(stored['confirmed_by'], payload['confirmed_by'])

    def test_expired_price_is_rejected(self):
        self.store.add_price(
            demo_item(item_id='expired-box', price_type='仕入', unit='箱'),
            '架空デモ担当', valid_from='2026-10-01', valid_until='2026-10-10',
        )
        with self.assertRaisesRegex(ValidationError, '期限切れ'):
            m02.run(self.payload(
                item_id='expired-box', source_unit='箱', base_unit='本', factor='4',
                evidence='simulator:架空値', as_of=DEMO_DATE,
            ), self.store)


if __name__ == '__main__':
    unittest.main()
