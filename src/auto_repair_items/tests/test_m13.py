"""M13 local JSON fixture connector and approval tests."""

import unittest

from auto_repair_items import m13
from auto_repair_items.core import Store, ValidationError


class M13Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_defaults_stage_only_fictional_purchase_candidate(self):
        result = m13.run(m13.SPEC['defaults'], self.store)

        self.assertTrue(result['simulator'])
        self.assertFalse(result['api_connected'])
        self.assertEqual(result['status'], '人の確認待ち')
        self.assertEqual(result['items'], [])
        self.assertEqual(self.store.price_versions(), [])
        candidate = result['staged_rows'][0]['item']
        self.assertEqual(candidate['price_type'], '仕入')
        self.assertTrue(candidate['source'].startswith('simulator:'))
        batch = self.store.latest('import_batch', result['import_batch_id'])
        self.assertEqual(batch['schema_version'], '1')
        self.assertEqual(batch['terms_status'], 'approved')

    def test_explicit_mapping_is_staged_then_human_approval_saves_price(self):
        payload = {
            'action': 'stage',
            'feed': {
                'mode': 'fixture', 'source': '架空卸A', 'terms_status': 'approved',
                'schema_version': '1',
                'offers': [{
                    'supplier_part_number': 'PART-7', 'unit_price': '125.50',
                    'currency': 'JPY', 'updated_at': '2026-10-10',
                    'customer_name': 'must never persist', 'raw_document': 'private source text',
                }],
            },
            'part_number_mapping': [{
                'supplier_part_number': 'PART-7', 'item_id': 'part-7',
                'name': '架空ブレーキ部品', 'category': '部品', 'unit': '個',
            }],
        }
        staged = m13.run(payload, self.store)
        candidate_id = staged['staged_rows'][0]['record_id']
        self.assertEqual(staged['staged_rows'][0]['status'], 'pending')
        self.assertEqual(self.store.price_versions(), [])
        stored_candidate = self.store.latest('staging_row', candidate_id)
        serialized_candidate = repr(stored_candidate)
        self.assertNotIn('must never persist', serialized_candidate)
        self.assertNotIn('private source text', serialized_candidate)

        approved = m13.run({
            'action': 'approve', 'import_batch_id': staged['import_batch_id'],
            'candidate_ids': [candidate_id], 'confirmed_by': '担当者',
        }, self.store)
        self.assertEqual(approved['items'][0]['price_type'], '仕入')
        self.assertEqual(approved['items'][0]['unit_price'], '125.50')
        self.assertEqual(self.store.price_versions()[0]['confirmed_by'], '担当者')

    def test_rejects_unapproved_live_unsupported_schema_or_bad_mapping(self):
        feed = dict(m13._DEMO_FEED)
        mapping = m13._DEMO_MAPPING
        bad_payloads = [
            {'action': 'stage', 'feed': {**feed, 'mode': 'live'}, 'part_number_mapping': mapping},
            {'action': 'stage', 'feed': {**feed, 'terms_status': 'unknown'}, 'part_number_mapping': mapping},
            {'action': 'stage', 'feed': {**feed, 'schema_version': '2'}, 'part_number_mapping': mapping},
            {'action': 'stage', 'feed': feed, 'part_number_mapping': []},
            {'action': 'stage', 'feed': feed, 'part_number_mapping': [{**mapping[0], 'unit': ''}]},
            {'action': 'stage', 'feed': {**feed, 'offers': [{**feed['offers'][0], 'unit_price': '0'}]}, 'part_number_mapping': mapping},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                m13.run(payload, self.store)
        self.assertEqual(self.store.price_versions(), [])
        self.assertEqual(self.store.records('staging_row'), [])

    def test_approval_cannot_select_candidate_from_another_batch(self):
        staged = m13.run(m13.SPEC['defaults'], self.store)
        with self.assertRaises(ValidationError):
            m13.run({
                'action': 'approve', 'import_batch_id': staged['import_batch_id'],
                'candidate_ids': ['unrelated-candidate'], 'confirmed_by': '担当者',
            }, self.store)
        self.assertEqual(self.store.price_versions(), [])


if __name__ == '__main__':
    unittest.main()
