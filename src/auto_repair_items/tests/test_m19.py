"""M19 panel-to-material dictionary tests."""

import unittest

from auto_repair_items import m19
from auto_repair_items.core import Store, ValidationError


class M19Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_default_lists_fictional_seed_candidate_without_price_or_quantity(self):
        result = m19.run(m19.SPEC['defaults'], self.store)
        self.assertEqual(result['candidates'][0]['item_id'], 'demo-metallic-paint')
        self.assertTrue(result['simulator'])
        self.assertNotIn('items', result)
        self.assertNotIn('unit_price', result['candidates'][0])
        self.assertNotIn('quantity', result['candidates'][0])

    def test_record_candidate_and_list_with_applicability_and_source(self):
        saved = m19.run({
            'action': 'record', 'panel_id': 'hood', 'finish_type': 'pearl',
            'item_id': 'paint-pearlescent', 'applicability': '下地確認後に使用',
            'source': '工場材料表 v2', 'confirmed_by': '整備士A',
        }, self.store)
        self.assertEqual(saved['status'], 'saved')
        listed = m19.run({'panel_id': 'hood', 'finish_type': 'pearl'}, self.store)
        self.assertEqual(listed['candidates'], [{
            'item_id': 'paint-pearlescent', 'applicability': '下地確認後に使用',
            'source': '工場材料表 v2', 'confirmed_by': '整備士A', 'simulator': False,
        }])

    def test_unregistered_pair_returns_empty_candidates_with_unknowns(self):
        result = m19.run({'panel_id': 'roof', 'finish_type': 'matte'}, self.store)
        self.assertEqual(result['candidates'], [])
        self.assertTrue(result['unknowns'])

    def test_selection_requires_human_confirmation_and_records_condition_and_source(self):
        m19.run({'action': 'record', 'panel_id': 'door', 'finish_type': 'solid',
                 'item_id': 'paint-red', 'applicability': '色合わせ後',
                 'source': '塗料台帳', 'confirmed_by': '担当A'}, self.store)
        selection = m19.run({
            'action': 'select', 'panel_id': 'door', 'finish_type': 'solid',
            'item_id': 'paint-red', 'application_condition': '色合わせを担当者が確認',
            'confirmed_by': '担当B',
        }, self.store)
        stored = self.store.latest('panel_material_selection', selection['selection_id'])
        self.assertEqual(stored['application_condition'], '色合わせを担当者が確認')
        self.assertEqual(stored['source'], '塗料台帳')
        self.assertEqual(stored['confirmed_by'], '担当B')
        self.assertNotIn('items', selection)

    def test_invalid_records_and_unlisted_selections_are_rejected(self):
        with self.assertRaises(ValidationError):
            m19.run({'action': 'record', 'panel_id': 'door', 'finish_type': 'solid',
                     'item_id': 'paint-red', 'applicability': 'ok', 'source': '',
                     'confirmed_by': '担当A'}, self.store)
        with self.assertRaises(ValidationError):
            m19.run({'action': 'select', 'panel_id': 'door', 'finish_type': 'solid',
                     'item_id': 'paint-red', 'application_condition': 'ok',
                     'confirmed_by': '担当A'}, self.store)


if __name__ == '__main__':
    unittest.main()
