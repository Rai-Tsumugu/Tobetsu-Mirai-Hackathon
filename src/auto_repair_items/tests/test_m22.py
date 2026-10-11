"""M22 operation-specific material proposal and human confirmation tests."""

import unittest

from auto_repair_items import m22
from auto_repair_items.core import Store, ValidationError, demo_item


class M22Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def record_rule(self, **changes):
        payload = {
            'action': 'register_rule', 'operation_id': 'paint', 'item_id': 'paint-a',
            'required_when': '塗装を行う場合', 'quantity_rule': '数量は人が入力',
            'evidence': '整備士確認の架空辞書', 'confirmed_by': '整備士A',
        }
        payload.update(changes)
        return m22.run(payload, self.store)

    def test_defaults_explicitly_register_fictional_mapping_only(self):
        result = m22.run(m22.SPEC['defaults'], self.store)
        self.assertEqual(result['status'], 'saved')
        self.assertTrue(result['simulator'])
        self.assertEqual(self.store.price_versions(), [])

    def test_suggest_uses_approved_operation_mapping_without_auto_adding_items(self):
        self.record_rule()
        before = self.store.records(m22.RULE_NAMESPACE)
        result = m22.run({'action': 'suggest', 'labor': {'breakdown': [
            {'operation': 'paint', 'hours': {}, 'reason': '確認済み', 'status': 'conditional'},
            {'operation': 'mask', 'hours': {}, 'reason': '未確認', 'status': 'unknown'},
        ]}}, self.store)
        self.assertEqual([row['item_id'] for row in result['suggestion']['candidates']], ['paint-a'])
        self.assertEqual(len(result['suggestion']['unknowns']), 1)
        self.assertEqual(self.store.records(m22.RULE_NAMESPACE), before)
        self.assertEqual(self.store.price_versions(), [])

    def test_proposed_mapping_is_nonpersistent_and_unknown_operation_gets_question(self):
        result = m22.run({'action': 'suggest', 'labor': {'breakdown': [
            {'operation': 'paint', 'status': 'confirmed'},
            {'operation': 'unknown-op', 'status': 'unknown'},
        ]}, 'proposed_rules': [{
            'operation_id': 'paint', 'item_id': 'fictional-item',
            'required_when': '架空条件', 'quantity_rule': '数量は人が選択',
            'evidence': 'simulator:fixture', 'confirmed_by': '架空デモ担当',
        }]}, self.store)
        self.assertEqual(result['suggestion']['candidates'][0]['mapping_status'], 'proposed')
        self.assertEqual(len(result['suggestion']['unknowns']), 1)
        self.assertEqual(self.store.records(m22.RULE_NAMESPACE), [])

    def test_confirm_selection_requires_human_quantity_and_matching_approved_price(self):
        self.record_rule()
        suggestion = m22.run({'action': 'suggest', 'labor': {'breakdown': [
            {'operation': 'paint', 'status': 'confirmed'},
        ]}}, self.store)['suggestion']
        self.store.add_price(demo_item('paint-a', '販売', '12.50', 'ml'), '価格担当')
        result = m22.run({'action': 'confirm_selection', 'suggestion_id': suggestion['suggestion_id'],
                          'operation_id': 'paint', 'item_id': 'paint-a', 'quantity': '2.4',
                          'unit': 'ml', 'confirmed_by': '整備士A'}, self.store)
        self.assertEqual(result['items'][0]['unit_price'], '12.50')
        self.assertEqual(result['material_snapshot']['candidate_amount'], '30.000')
        self.assertEqual(result['material_snapshot']['quantity'], '2.4')
        self.assertEqual(result['material_snapshot']['price_version_id'],
                         self.store.price_versions('paint-a')[0]['price_version_id'])
        self.assertFalse(result['material_snapshot']['labor_cost_included'])
        self.assertEqual(result['quantity_snapshot_ref'], result['snapshot_id'])

    def test_confirmation_rejects_unoffered_item_missing_price_and_unit_mismatch(self):
        self.record_rule()
        suggestion = m22.run({'action': 'suggest', 'labor': {'breakdown': [
            {'operation': 'paint', 'status': 'confirmed'},
        ]}}, self.store)['suggestion']
        with self.assertRaises(ValidationError):
            m22.run({'action': 'confirm_selection', 'suggestion_id': suggestion['suggestion_id'],
                     'operation_id': 'paint', 'item_id': 'other', 'quantity': '2', 'unit': 'ml',
                     'confirmed_by': '整備士A'}, self.store)
        self.store.add_price(demo_item('paint-a', '販売', '12', 'L'), '価格担当')
        with self.assertRaises(ValidationError):
            m22.run({'action': 'confirm_selection', 'suggestion_id': suggestion['suggestion_id'],
                     'operation_id': 'paint', 'item_id': 'paint-a', 'quantity': '2', 'unit': 'ml',
                     'confirmed_by': '整備士A'}, self.store)
        self.assertEqual(self.store.records(m22.SNAPSHOT_NAMESPACE), [])

    def test_decimal_quantity_is_positive_and_unit_is_required(self):
        self.record_rule()
        suggestion = m22.run({'action': 'suggest', 'labor': {'breakdown': [
            {'operation': 'paint', 'status': 'confirmed'},
        ]}}, self.store)['suggestion']
        self.store.add_price(demo_item('paint-a', '販売', '12', 'ml'), '価格担当')
        common = {'action': 'confirm_selection', 'suggestion_id': suggestion['suggestion_id'],
                  'operation_id': 'paint', 'item_id': 'paint-a', 'confirmed_by': '整備士A'}
        for changes in ({'quantity': '0', 'unit': 'ml'}, {'quantity': '1.5', 'unit': ''}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                m22.run(dict(common, **changes), self.store)


if __name__ == '__main__':
    unittest.main()
