from decimal import Decimal
import tempfile
from pathlib import Path
import unittest
from auto_repair_items.core import Store, ValidationError, demo_item, decimal_value, validate_item


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_contract_rejects_unknown_and_invalid(self):
        for value in (None, '', '-1', 'NaN', 'Infinity', True):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_item(demo_item(unit_price=value))
        self.assertEqual(decimal_value('0.001'), Decimal('0.001'))

    def test_sale_missing_and_expiry_do_not_fallback(self):
        self.store.add_price(demo_item(price_type='仕入'), 'demo')
        with self.assertRaises(ValidationError):
            self.store.get_price('demo-paint')
        self.store.add_price(demo_item(), 'demo', valid_until='2026-10-12')
        self.store.add_price(demo_item(unit_price='140'), 'demo', valid_from='2026-10-12', valid_until='2026-10-13')
        with self.assertRaises(ValidationError):
            self.store.get_price('demo-paint', as_of='2026-10-14')

    def test_future_pending_units_and_suppliers(self):
        self.store.add_price(demo_item(unit_price='1'), 'demo', valid_from='2026-10-13')
        self.store.add_price(demo_item(unit_price='2'), 'demo', status='pending')
        with self.assertRaises(ValidationError):
            self.store.get_price('demo-paint')
        self.store.add_price(demo_item(), 'demo', supplier_id='A')
        self.store.add_price(demo_item(), 'demo', supplier_id='B')
        with self.assertRaises(ValidationError):
            self.store.get_price('demo-paint')
        with self.assertRaises(ValidationError):
            self.store.get_price('demo-paint', supplier_id='A', unit='L')

    def test_nested_rollback_and_persistence(self):
        with self.assertRaises(ValidationError):
            with self.store.transaction():
                self.store.put('test', {'value': '1'})
                self.store.add_price(demo_item(), 'demo')
                raise ValidationError('rollback')
        self.assertEqual(self.store.records('test'), [])
        self.assertEqual(self.store.price_versions(), [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.db'
            first = Store(path)
            version = first.add_price(demo_item(unit_price='0.123'), 'demo')
            first.close()
            second = Store(path)
            self.assertEqual(second.get_price('demo-paint')['price_version_id'], version['price_version_id'])
            self.assertEqual(second.get_price('demo-paint')['item']['unit_price'], '0.123')
            second.close()

    def test_non_yen_price_is_not_used_as_yen(self):
        self.store.add_price(demo_item(), 'demo', currency='USD')
        with self.assertRaises(ValidationError):
            self.store.get_price('demo-paint')


if __name__ == '__main__':
    unittest.main()
