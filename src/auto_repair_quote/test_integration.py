"""Cross-feature pricing and immutable persistence regressions."""
import copy
import sqlite3
import unittest
from .fixtures import demo_inputs
from .pipeline import calculate
from .store import QuoteStore

class IntegrationTests(unittest.TestCase):
    def test_band_calculation_wait_exclusion_and_input_immutability(self):
        inputs = demo_inputs()
        original = copy.deepcopy(inputs)
        quote = calculate(inputs)
        self.assertEqual(quote['status'], 'proposed')
        self.assertEqual(quote['total'], {'low':9900,'typical':14300,'high':23100})
        self.assertEqual(inputs, original)
        inputs['labor']['elapsed_hours'] = {'low':100,'typical':200,'high':300}
        self.assertEqual(calculate(inputs)['total'], quote['total'])

    def test_missing_prices_and_units_are_blocked_without_zero_substitution(self):
        for field in ('unit_price', 'quantity_unit'):
            inputs = demo_inputs()
            inputs['items'][0][field] = None
            quote = calculate(inputs)
            self.assertEqual(quote['status'], 'blocked')
            self.assertTrue(all(amount is None for amount in quote['total'].values()))

    def test_purchase_price_is_applied_once_and_discounts_recompute_tax(self):
        inputs = demo_inputs()
        inputs['items'][0].update(price_type='仕入',markup={'value':1.5,'approved_by':'demo','reason':'架空'})
        inputs['discount'] = {'scope':'subtotal','line_ids':[],'kind':'rate','value':.1,'reason':'架空','approved_by':'demo','order':'before_tax'}
        quote = calculate(inputs)
        self.assertEqual(quote['status'],'proposed',quote.get('issues'))
        self.assertEqual(quote['subtotal']['typical'],12150)
        self.assertEqual(quote['tax']['typical'],1215)
        self.assertEqual(quote['total']['typical'],13365)

    def test_factory_tax_discount_preserves_explicit_tax_targets(self):
        inputs = demo_inputs()
        inputs['tax_policy'] = {'source':'factory','rate':.1,'rounding':'floor',
            'approved_by':'demo','effective_date':'2026-10-11',
            'taxable_line_ids':['labor-breakdown:1','item:SIM-PART-001']}
        # P04 generated item IDs are read from the authoritative base quote.
        base = calculate(demo_inputs())
        inputs['tax_policy']['taxable_line_ids'] = [line['line_id'] for line in base['lines']]
        inputs['discount'] = {'scope':'subtotal','line_ids':[],'kind':'rate','value':.1,
            'reason':'架空','approved_by':'demo','order':'before_tax'}
        quote = calculate(inputs)
        self.assertEqual(quote['status'],'proposed',quote.get('issues'))
        self.assertEqual(quote['subtotal']['typical'],11700)
        self.assertEqual(quote['tax']['typical'],1170)
        self.assertEqual(quote['total']['typical'],12870)
        inputs['tax_policy']['taxable_line_ids'] = [base['lines'][0]['line_id']]
        self.assertEqual(calculate(inputs)['status'],'blocked')

    def test_immutable_versions_foreign_keys_and_transaction_rollback(self):
        store = QuoteStore()
        quote = calculate(demo_inputs())
        store.save_quote(quote)
        quote['total']['low'] = 0
        self.assertEqual(store.get_quote('demo',1)['total']['low'],9900)
        with self.assertRaises(sqlite3.IntegrityError):
            store.save_quote(quote)
        with self.assertRaises(sqlite3.IntegrityError):
            store.append_communication({'communication_id':'x','quote_id':'absent','quote_version':1})
        with self.assertRaises(RuntimeError):
            with store.transaction():
                next_quote = copy.deepcopy(quote)
                next_quote['quote_version'] = 2
                store.save_quote(next_quote)
                raise RuntimeError('rollback')
        with self.assertRaises(ValueError):
            store.get_quote('demo',2)
        store.close()
