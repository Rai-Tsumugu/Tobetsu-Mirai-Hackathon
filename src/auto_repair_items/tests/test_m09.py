"""Acceptance tests for M09 CSV column mapping and human approval."""

import unittest

from auto_repair_items import m09
from auto_repair_items.core import ITEM_FIELDS, Store, ValidationError, seed_demo


class M09Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        seed_demo(self.store)

    def tearDown(self):
        self.store.close()

    def test_spec_defaults_stage_candidates_without_auto_approval(self):
        result = m09.run(m09.SPEC['defaults'], self.store)

        self.assertEqual(result['status'], '人の確認待ち')
        self.assertEqual(result['preview_count'], 2)
        self.assertEqual(result['quarantined_count'], 0)
        self.assertEqual(result['mapping_version'], 1)
        self.assertEqual(result['items'], [])
        self.assertEqual(self.store.price_versions('demo-m09-paint'), [])
        self.assertEqual(self.store.price_versions('demo-m09-thinner'), [])
        self.assertTrue(all(row['status'] == 'pending' for row in result['staged_rows']))

    def test_column_map_normalizes_rows_and_does_not_store_unmapped_data(self):
        payload = dict(m09.SPEC['defaults'])
        lines = payload['csv_text'].splitlines()
        lines[1] += ',customer@example.invalid'
        payload['csv_text'] = '\n'.join(lines)
        # The appended malformed row is quarantined; its extra column value is
        # discarded before persistence.
        result = m09.run(payload, self.store)

        first = next(row for row in result['staged_rows'] if row['status'] == 'pending')
        self.assertEqual(set(first['item']), set(ITEM_FIELDS))
        serialized = repr(self.store.records('staging_row'))
        self.assertNotIn('customer@example.invalid', serialized)
        self.assertEqual(result['quarantined_count'], 1)

    def test_invalid_price_is_quarantined_and_selected_valid_row_can_be_approved(self):
        payload = dict(m09.SPEC['defaults'])
        payload['csv_text'] = payload['csv_text'].replace(',95,', ',-95,')
        staged = m09.run(payload, self.store)
        valid = next(row for row in staged['staged_rows'] if row['status'] == 'pending')
        invalid = next(row for row in staged['staged_rows'] if row['status'] == 'quarantined')

        approved = m09.run({
            'action': 'approve',
            'candidate_ids': [valid['record_id']],
            'confirmed_by': '架空確認担当',
            'source_key': staged['source_key'],
            'mapping_version': staged['mapping_version'],
        }, self.store)

        self.assertEqual(len(approved['items']), 1)
        self.assertEqual(approved['items'][0]['item_id'], valid['item']['item_id'])
        self.assertEqual(approved['mapping_version'], 1)
        self.assertEqual(self.store.price_versions('demo-m09-paint'), [])
        self.assertEqual(self.store.price_versions(valid['item']['item_id'])[0]['confirmed_by'], '架空確認担当')

    def test_reimport_appends_a_new_mapping_version(self):
        first = m09.run(m09.SPEC['defaults'], self.store)
        second = m09.run(m09.SPEC['defaults'], self.store)

        self.assertEqual(first['mapping_version'], 1)
        self.assertEqual(second['mapping_version'], 2)
        mappings = self.store.records('import_mapping', 'demo-m09-csv')
        self.assertEqual([record['version'] for record in mappings], [1, 2])

    def test_bad_headers_mapping_csv_and_payload_are_rejected(self):
        base = dict(m09.SPEC['defaults'])
        invalid_payloads = [
            None,
            base | {'csv_text': 'a,a\n1,2', 'field_map': {}},
            base | {'csv_text': 'a,b\n"unterminated,b', 'field_map': {}},
            base | {'field_map': {'unknown': '品名'}},
            base | {'field_map': {'item_id': 'absent'}},
            base | {'action': 'guess'},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                m09.run(payload, self.store)
        self.assertEqual(self.store.records('import_mapping'), [])

    def test_bad_mapping_version_is_rejected_before_approval(self):
        staged = m09.run(m09.SPEC['defaults'], self.store)
        candidate_id = staged['staged_rows'][0]['record_id']

        with self.assertRaises(ValidationError):
            m09.run({
                'action': 'approve', 'candidate_ids': [candidate_id],
                'confirmed_by': '架空確認担当', 'source_key': staged['source_key'],
                'mapping_version': 99,
            }, self.store)

        self.assertEqual(self.store.price_versions('demo-m09-paint'), [])

    def test_approval_requires_an_explicit_nonempty_candidate_selection(self):
        with self.assertRaises(ValidationError):
            m09.run({
                'action': 'approve', 'candidate_ids': [], 'confirmed_by': '架空確認担当',
            }, self.store)
        self.assertEqual(self.store.price_versions('demo-m09-paint'), [])


if __name__ == '__main__':
    unittest.main()
