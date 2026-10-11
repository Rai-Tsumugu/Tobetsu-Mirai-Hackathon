"""M11 PDF region simulator and human approval tests."""

import unittest

from auto_repair_items import m11
from auto_repair_items.core import Store, ValidationError


class M11Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_defaults_make_mock_candidates_without_adding_prices(self):
        result = m11.run(m11.SPEC['defaults'], self.store)

        self.assertTrue(result['simulator'])
        self.assertFalse(result['extraction_connected'])
        self.assertEqual(result['page'], 1)
        self.assertEqual(result['staged_rows'][0]['status'], 'pending')
        self.assertEqual(result['items'], [])
        self.assertEqual(self.store.price_versions(), [])
        batch = self.store.latest('import_batch', result['import_batch_id'])
        self.assertEqual(batch['source_document_id'], 'demo-m11-pdf')
        self.assertNotIn('raw_text', batch)

    def test_stage_validates_reference_and_bounds_then_human_selects_candidate(self):
        result = m11.run({
            'action': 'stage', 'source_document_id': 'opaque-doc-42', 'page': 2,
            'page_width': '612', 'page_height': '792',
            'region': {'x': '20', 'y': '40', 'width': '300', 'height': '120'},
        }, self.store)
        row = result['staged_rows'][0]
        self.assertEqual(result['source_document_id'], 'opaque-doc-42')
        self.assertEqual(self.store.latest('staging_row', row['record_id'])['item']['source'],
                         'simulator:未接続のPDF抽出、架空値')
        self.assertEqual(self.store.price_versions(), [])

        approved = m11.run({
            'action': 'approve', 'import_batch_id': result['import_batch_id'],
            'candidate_ids': [row['record_id']], 'confirmed_by': '担当者',
        }, self.store)
        self.assertEqual(approved['items'][0]['item_id'], 'demo-m11-paint')
        self.assertEqual(self.store.price_versions()[0]['confirmed_by'], '担当者')

    def test_rejects_invalid_page_region_and_unrelated_candidate(self):
        base = {
            'action': 'stage', 'source_document_id': 'opaque-doc-42', 'page': 1,
            'page_width': '612', 'page_height': '792',
            'region': {'x': '20', 'y': '40', 'width': '300', 'height': '120'},
        }
        invalid_payloads = (
            {**base, 'page': 0},
            {**base, 'region': {'x': '600', 'y': '40', 'width': '20', 'height': '120'}},
            {**base, 'region': {'x': '20', 'y': '40', 'width': '0', 'height': '120'}},
            {**base, 'source_document_id': '   '},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                m11.run(payload, self.store)
        result = m11.run(base, self.store)
        with self.assertRaises(ValidationError):
            m11.run({
                'action': 'approve', 'import_batch_id': result['import_batch_id'],
                'candidate_ids': ['not-a-candidate'], 'confirmed_by': '担当者',
            }, self.store)
        self.assertEqual(self.store.price_versions(), [])


if __name__ == '__main__':
    unittest.main()
