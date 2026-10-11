"""M12 mock OCR privacy, review queue, and human-gated registration tests."""

import unittest

from auto_repair_items import m12
from auto_repair_items.core import ITEM_FIELDS, Store, ValidationError


class M12Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def stage(self, **changes):
        payload = dict(m12.SPEC['defaults'])
        payload.update(changes)
        return m12.run(payload, self.store)

    def review(self, candidate_id, fields, reviewer='架空確認担当'):
        return m12.run({
            'action': 'review', 'candidate_id': candidate_id,
            'fields': fields, 'confirmed_by': reviewer,
        }, self.store)

    def test_defaults_are_mock_candidates_and_do_not_register(self):
        result = self.stage()

        self.assertEqual(result['status'], '人の確認待ち')
        self.assertFalse(result['ocr_connected'])
        self.assertTrue(result['simulator'])
        self.assertEqual(result['missing_fields'], list(ITEM_FIELDS))
        self.assertEqual(result['items'], [])
        self.assertEqual(self.store.price_versions(), [])
        queued = self.store.latest('m12_ocr_queue', result['candidate_id'])
        self.assertEqual(queued['status'], 'pending')

    def test_low_confidence_and_missing_values_are_blank_and_unconfirmed(self):
        fields = dict(m12.SPEC['defaults']['ocr_fields'])
        fields['unit_price'] = {'value': '480', 'confidence': '0.4'}
        fields.pop('unit')
        result = self.stage(ocr_fields=fields)

        self.assertIsNone(result['candidates']['unit_price']['candidate_value'])
        self.assertIsNone(result['candidates']['unit']['candidate_value'])
        self.assertEqual(self.store.price_versions(), [])

    def test_each_field_requires_human_confirmation_and_only_complete_review_registers(self):
        staged = self.stage()
        candidate_id = staged['candidate_id']
        first_batch = {field: {'corrected_value': staged['candidates'][field]['candidate_value'],
                               'confirmed': True}
                       for field in ITEM_FIELDS[:-1]}
        partial = self.review(candidate_id, first_batch)

        self.assertEqual(partial['status'], '人の確認待ち')
        self.assertEqual(partial['missing_fields'], ['updated_at'])
        self.assertEqual(partial['items'], [])
        self.assertEqual(self.store.price_versions(), [])

        completed = self.review(candidate_id, {
            'updated_at': {'corrected_value': '2026-10-11', 'confirmed': True},
        }, reviewer='最終確認者')
        self.assertEqual(completed['status'], 'approved')
        self.assertEqual(set(completed['items'][0]), set(ITEM_FIELDS))
        self.assertEqual(completed['reviewer'], '最終確認者')
        versions = self.store.price_versions('demo-m12-thinner', '仕入')
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]['confirmed_by'], '最終確認者')

    def test_corrections_and_reviewers_are_append_only(self):
        staged = self.stage()
        candidate_id = staged['candidate_id']
        first = self.review(candidate_id, {
            'name': {'corrected_value': '架空溶剤A', 'confirmed': True},
        }, reviewer='確認者A')
        second = self.review(candidate_id, {
            'name': {'corrected_value': '架空溶剤B', 'confirmed': True},
        }, reviewer='確認者B')

        self.assertEqual(first['status'], '人の確認待ち')
        self.assertEqual(second['corrected_value']['name'], '架空溶剤B')
        history = self.store.records('m12_ocr_review', candidate_id)
        self.assertEqual([record['reviewer'] for record in history], ['確認者A', '確認者B'])
        self.assertEqual(history[0]['corrected_value']['name'], '架空溶剤A')

    def test_full_invoice_text_is_rejected_and_never_persisted(self):
        payload = dict(m12.SPEC['defaults'])
        payload['raw_text'] = 'customer@example.invalid 伝票全文'
        with self.assertRaises(ValidationError):
            m12.run(payload, self.store)
        self.assertNotIn('customer@example.invalid', repr(self.store.records('m12_ocr_queue')))

    def test_invalid_values_or_unconfirmed_fields_do_not_register(self):
        staged = self.stage()
        candidate_id = staged['candidate_id']
        with self.assertRaises(ValidationError):
            self.review(candidate_id, {
                'unit_price': {'corrected_value': '0', 'confirmed': True},
                'item_id': {'corrected_value': 'bad-id', 'confirmed': False},
            })
        self.assertEqual(self.store.price_versions(), [])
        with self.assertRaises(ValidationError):
            self.review(candidate_id, {
                'unit_price': {'corrected_value': '-1', 'confirmed': True},
            })
        self.assertEqual(self.store.price_versions(), [])

    def test_invalid_payload_action_and_unknown_fields_are_rejected(self):
        for payload in (None, {'action': 'guess'}, {'action': 'review', 'candidate_id': 'missing'}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                m12.run(payload, self.store)
        with self.assertRaises(ValidationError):
            self.stage(ocr_fields={'customer_email': {'value': 'person@example.invalid', 'confidence': '1'}})


if __name__ == '__main__':
    unittest.main()
