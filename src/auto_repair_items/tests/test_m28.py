"""M28 versioned markup rule and human approval tests."""

import unittest
from decimal import Decimal

from auto_repair_items import m28
from auto_repair_items.core import Store, ValidationError, demo_item


class M28Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.purchase = self.store.add_price(
            demo_item(item_id='paint-x', price_type='仕入', unit_price='80.25'),
            '仕入確認者', supplier_id='supplier-x', valid_from='2026-09-01',
        )

    def tearDown(self):
        self.store.close()

    def rule(self, **updates):
        return m28.run({
            'action': 'record_rule', 'rule_id': 'rule-x', 'category': '塗料',
            'supplier_id': 'supplier-x', 'effective_from': '2026-09-01',
            'multiplier': '1.25', 'confirmed_by': '社長', 'reason': '人が決めた架空ルール',
        } | updates, self.store)['rule']

    def propose(self, **updates):
        return m28.run({
            'action': 'propose', 'item_id': 'paint-x',
            'purchase_price_version_id': self.purchase['price_version_id'],
            'rule_id': 'rule-x', 'as_of': '2026-10-01',
            'reason': '候補提示の理由',
        } | updates, self.store)

    def test_rule_versions_are_append_only_and_preserve_scope_and_confirmers(self):
        first = self.rule()
        second = self.rule(effective_from='2026-10-01', multiplier='1.5', reason='価格方針更新')
        self.assertEqual((first['version'], second['version']), (1, 2))
        self.assertEqual(second['confirmed_by'], '社長')
        self.assertEqual(len(self.store.records(m28.RULES, 'rule-x')), 2)

    def test_proposal_uses_exact_effective_rule_and_never_saves_sales_price(self):
        self.rule()
        self.rule(effective_from='2026-10-01', multiplier='1.5')
        result = self.propose()
        proposal = result['proposal']
        self.assertEqual((proposal['rule_version'], proposal['multiplier']), (2, '1.5'))
        self.assertEqual(Decimal(result['items'][0]['unit_price']), Decimal('120.375'))
        self.assertEqual(set(result['items'][0]), {
            'item_id', 'name', 'category', 'unit', 'unit_price', 'price_type', 'source', 'updated_at'
        })
        self.assertFalse(result['price_saved'])
        self.assertEqual(self.store.price_versions('paint-x', '販売'), [])
        self.assertEqual(proposal['purchase_price_version_id'], self.purchase['price_version_id'])

    def test_approval_saves_sales_price_once_with_full_trace(self):
        self.rule()
        proposal = self.propose()['proposal']
        approved = m28.run({
            'action': 'approve', 'proposal_id': proposal['proposal_id'],
            'confirmed_by': '社長', 'reason': '候補を確認して承認',
        }, self.store)
        version = approved['price_version']
        self.assertTrue(approved['price_saved'])
        self.assertEqual(version['item']['unit_price'], '100.3125')
        self.assertEqual(version['item']['price_type'], '販売')
        self.assertEqual(version['confirmed_by'], '社長')
        self.assertEqual(version['reason'], '候補を確認して承認')
        self.assertEqual(version['metadata']['markup_rule_version'], 1)
        self.assertEqual(version['metadata']['purchase_price_version_id'], self.purchase['price_version_id'])
        self.assertEqual(version['metadata']['applied_on'], '2026-10-01')
        with self.assertRaisesRegex(ValidationError, '承認待ち'):
            m28.run({'action': 'approve', 'proposal_id': proposal['proposal_id'],
                     'confirmed_by': '社長', 'reason': '二重承認'}, self.store)

    def test_existing_sales_price_blocks_both_candidate_and_approval(self):
        self.rule()
        existing = demo_item(item_id='paint-x', price_type='販売', unit_price='90')
        existing['updated_at'] = '2026-09-15'
        self.store.add_price(existing, '社長', supplier_id='other-supplier', valid_from='2026-09-15')
        with self.assertRaisesRegex(ValidationError, '既にある'):
            self.propose()

    def test_missing_or_mismatched_rule_and_explicit_fields_are_rejected(self):
        with self.assertRaisesRegex(ValidationError, 'ルール'):
            self.propose()
        self.rule()
        with self.assertRaisesRegex(ValidationError, '対象カテゴリ'):
            self.propose(rule_id='missing-rule')
        with self.assertRaises(ValidationError):
            self.rule(effective_from='2026-08-01')
        with self.assertRaises(ValidationError):
            m28.run(m28.SPEC['defaults'] | {'multiplier': '0'}, self.store)
        with self.assertRaises(ValidationError):
            m28.run(m28.SPEC['defaults'] | {'unapproved_multiplier': '2'}, self.store)

    def test_wrong_supplier_category_and_unknown_action_do_not_write(self):
        self.rule()
        other_supplier_purchase = self.store.add_price(
            demo_item(item_id='paint-y', price_type='仕入', unit_price='20'),
            '仕入確認者', supplier_id='supplier-y',
        )
        with self.assertRaisesRegex(ValidationError, 'ルール'):
            self.propose(item_id='paint-y', purchase_price_version_id=other_supplier_purchase['price_version_id'])
        with self.assertRaises(ValidationError):
            self.rule(category='部品')
        with self.assertRaises(ValidationError):
            m28.run({'action': 'automatic_markup'}, self.store)
        self.assertEqual(self.store.records(m28.PROPOSALS), [])


if __name__ == '__main__':
    unittest.main()
