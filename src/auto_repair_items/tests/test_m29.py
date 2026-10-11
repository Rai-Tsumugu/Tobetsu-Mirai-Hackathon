"""M29 tests for approved, versioned decimal rounding rules."""

import unittest

from auto_repair_items.core import Store, ValidationError
from auto_repair_items.m29 import QUOTE_NAMESPACE, RULE_NAMESPACE, SPEC, run


class M29Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def save_rule(self, rule_id, stage, *, mode='half_up', places=2, confirmer='会計担当'):
        return run({'action': 'save_rule', 'id': rule_id, 'stage': stage,
                    'mode': mode, 'decimal_places': places,
                    'confirmed_by': confirmer}, self.store)['rounding_rule']

    def quote_payload(self, **changes):
        payload = {
            'action': 'quote', 'quote_id': 'quote-a',
            'line_rule_id': 'line-rule', 'tax_rule_id': 'tax-rule',
            'confirmed_by': '見積担当', 'tax_rates': {'tax-a': '0.1'},
            'lines': [
                {'quote_line_id': 'line-a', 'name': '材料A', 'quantity': '1',
                 'unit_price': '1.005', 'tax_category': 'tax-a'},
                {'quote_line_id': 'line-b', 'name': '材料B', 'quantity': '1',
                 'unit_price': '1.005', 'tax_category': 'tax-a'},
            ],
        }
        payload.update(changes)
        return payload

    def setup_rules(self):
        self.save_rule('line-rule', 'line')
        self.save_rule('tax-rule', 'tax_category_total')

    def test_save_rule_keeps_approved_versions_append_only(self):
        first = self.save_rule('line-rule', 'line')
        second = self.save_rule('line-rule', 'line', mode='down', confirmer='担当B')

        self.assertNotEqual(first['rounding_rule_version_id'], second['rounding_rule_version_id'])
        self.assertEqual(len(self.store.records(RULE_NAMESPACE, 'line-rule')), 2)
        self.assertEqual(self.store.latest(RULE_NAMESPACE, 'line-rule')['confirmed_by'], '担当B')

    def test_quote_preserves_unrounded_products_and_records_rule_versions(self):
        line_rule = self.save_rule('line-rule', 'line')
        tax_rule = self.save_rule('tax-rule', 'tax_category_total')

        result = run(self.quote_payload(), self.store)['quote']

        self.assertEqual([line['unrounded_line_total'] for line in result['lines']], ['1.005', '1.005'])
        self.assertEqual([line['line_total'] for line in result['lines']], ['1.01', '1.01'])
        # Per-line half-up yields 2.02; rounding the combined base 2.010 would yield 2.01.
        self.assertEqual(result['subtotal'], '2.02')
        self.assertEqual(result['tax_groups'][0]['unrounded_tax'], '0.2010')
        self.assertEqual(result['tax'], '0.20')
        self.assertEqual(result['total'], '2.22')
        self.assertEqual(result['rounding_rules']['line']['rounding_rule_version_id'],
                         line_rule['rounding_rule_version_id'])
        self.assertEqual(result['rounding_rules']['tax_category_total']['rounding_rule_version_id'],
                         tax_rule['rounding_rule_version_id'])
        self.assertEqual(result['lines'][0]['rounding_rule']['id'], 'line-rule')
        self.assertEqual(result['tax_groups'][0]['rounding_rule']['id'], 'tax-rule')
        self.assertEqual(self.store.latest(QUOTE_NAMESPACE, 'quote-a'), result)
        self.assertEqual(result['tax_rate_source'], 'human_supplied_fictional_configuration')

    def test_rule_stage_must_match_quote_stage(self):
        self.save_rule('line-rule', 'tax_category_total')
        self.save_rule('tax-rule', 'tax_category_total')
        with self.assertRaises(ValidationError):
            run(self.quote_payload(), self.store)
        self.assertEqual(self.store.records(QUOTE_NAMESPACE), [])

    def test_missing_approval_or_invalid_rule_is_rejected(self):
        for changes in (
            {'confirmed_by': ''}, {'id': ''}, {'stage': 'total'},
            {'mode': 'truncate'}, {'decimal_places': -1}, {'decimal_places': 1.5},
        ):
            payload = {'action': 'save_rule', 'id': 'line-rule', 'stage': 'line',
                       'mode': 'half_up', 'decimal_places': 2, 'confirmed_by': '担当'}
            payload.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                run(payload, self.store)
        self.assertEqual(self.store.records(RULE_NAMESPACE), [])

    def test_negative_nan_unapproved_and_invalid_tax_rates_do_not_save_quote(self):
        self.setup_rules()
        invalid_payloads = (
            self.quote_payload(confirmed_by=''),
            self.quote_payload(lines=[dict(self.quote_payload()['lines'][0], quantity='-1')]),
            self.quote_payload(lines=[dict(self.quote_payload()['lines'][0], unit_price='NaN')]),
            self.quote_payload(tax_rates={'tax-a': 'Infinity'}),
            self.quote_payload(tax_rates={'tax-a': '1.1'}),
            self.quote_payload(lines=[dict(self.quote_payload()['lines'][0], tax_category='missing')]),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                run(payload, self.store)
        self.assertEqual(self.store.records(QUOTE_NAMESPACE), [])

    def test_explicit_demo_uses_only_fictional_seed_data(self):
        result = run(SPEC['defaults'], self.store)

        self.assertTrue(result['simulator'])
        quote = result['quote']
        self.assertEqual(quote['subtotal'], '2.02')
        self.assertEqual(quote['tax'], '0.20')
        self.assertEqual(len(self.store.records(RULE_NAMESPACE, 'demo-m29-line-rule')), 1)


if __name__ == '__main__':
    unittest.main()
