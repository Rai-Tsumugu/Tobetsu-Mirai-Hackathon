"""End-to-end checks for the unified inventory and quote workflow."""

import unittest

from auto_repair_items.core import DEMO_DATE, Store, ValidationError
from auto_repair_items.integrated import IMPORT_BATCH_NAMESPACE, run


class IntegratedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def item(self, price='120', price_type='販売'):
        return {'item_id': 'paint-1', 'name': '塗料A', 'category': '塗料', 'unit': 'ml',
                'unit_price': price, 'price_type': price_type, 'source': 'supplier:sample',
                'updated_at': DEMO_DATE}

    def test_register_quote_update_keeps_snapshot_and_records_usage(self):
        for price_type, price in [('販売', '120.125'), ('仕入', '80')]:
            run({'action': 'register', 'item': self.item(price, price_type),
                 'confirmed_by': '担当A', 'reason': '初回確認', 'conditions': {
                     'currency': 'JPY', 'freight_basis': 'included'}}, self.store)
        saved = run({'action': 'save_quote', 'quote_id': 'q-1', 'confirmed_by': '担当A',
                     'lines': [{'item_id': 'paint-1', 'quantity': '2.5', 'unit': 'ml',
                                'price_type': '販売'}]}, self.store)['quote']
        line = saved['lines'][0]
        self.assertEqual(line['line_total'], '300.3125')
        run({'action': 'update_price', 'item': self.item('130.50'), 'confirmed_by': '担当B',
             'reason': '仕入先価格改定', 'checked_at': '2026-10-11'}, self.store)
        retrieved = run({'action': 'get_quote', 'quote_id': 'q-1'}, self.store)['quote']
        self.assertEqual(retrieved['lines'][0]['unit_price_snapshot'], '120.125')
        self.assertEqual(retrieved['lines'][0]['conditions'], {'currency': 'JPY', 'freight_basis': 'included'})
        dashboard = run({'action': 'dashboard'}, self.store)
        new_price = next(row for row in dashboard['inventory'] if row['price_version_id'] != line['price_version_id']
                         and row['price_type'] == '販売')
        self.assertEqual(new_price['age_days'], 0)
        self.assertNotIn('価格確認日不明', new_price['issues'])
        usage = run({'action': 'record_usage', 'quote_id': 'q-1', 'quote_line_id': line['quote_line_id'],
                     'actual_qty': '2.25', 'confirmed_by': '担当A', 'reason': '作業実績'}, self.store)
        self.assertEqual(usage['comparison']['difference'], '-0.25')
        self.assertEqual(self.store.latest('quote_snapshot', 'q-1')['lines'][0]['quantity'], '2.5')

    def test_future_confirmation_is_flagged(self):
        run({'action': 'register', 'item': self.item(), 'confirmed_by': '担当',
             'reason': '確認', 'checked_at': '2026-10-12'}, self.store)
        result = run({'action': 'dashboard', 'as_of': '2026-10-11'}, self.store)
        self.assertIn('確認日が適用日より未来', result['inventory'][0]['issues'])
        self.assertNotEqual(result['inventory'][0]['freshness'], 'current')

    def test_import_approval_is_batch_owned_and_atomic(self):
        headers = 'item_id,name,category,unit,unit_price,price_type,source,updated_at'
        rows = f'{headers}\npart-1,部品A,部品,個,10,仕入,supplier:csv,{DEMO_DATE}\npart-2,部品B,部品,個,20,仕入,supplier:csv,{DEMO_DATE}'
        staged = run({'action': 'stage_csv', 'csv_text': rows, 'source': 'supplier:csv',
                      'source_key': 'supplier-csv', 'import_batch_id': 'batch-a'}, self.store)
        ids = [row['record_id'] for row in staged['staged_rows']]
        outsider = run({'action': 'stage_csv', 'csv_text': rows, 'source': 'supplier:csv',
                        'source_key': 'supplier-csv-2', 'import_batch_id': 'batch-b'}, self.store)
        second_same_source = run({'action': 'stage_csv', 'csv_text': rows, 'source': 'supplier:csv',
                                  'source_key': 'supplier-csv', 'import_batch_id': 'batch-c'}, self.store)
        before = self.store.price_versions()
        with self.assertRaises(ValidationError):
            run({'action': 'approve_import', 'import_batch_id': 'batch-a',
                 'candidate_ids': [ids[0], outsider['staged_rows'][0]['record_id']], 'confirmed_by': '担当'}, self.store)
        self.assertEqual(self.store.price_versions(), before)
        approved = run({'action': 'approve_import', 'import_batch_id': 'batch-a',
                        'candidate_ids': ids, 'confirmed_by': '担当'}, self.store)
        self.assertEqual(len(approved['price_version_ids']), 2)
        self.assertEqual(len(self.store.records(IMPORT_BATCH_NAMESPACE, 'batch-a')), 2)
        self.assertNotEqual(staged['import_batch_id'], second_same_source['import_batch_id'])

    def test_dashboard_is_read_only_and_reports_invalid_price(self):
        run({'action': 'register', 'item': self.item('100'), 'confirmed_by': '担当', 'reason': '旧価格',
             'valid_from': '2026-10-01', 'checked_at': '2026-10-01'}, self.store)
        run({'action': 'update_price', 'item': self.item(), 'confirmed_by': '担当', 'reason': '期限切れ',
             'valid_from': '2026-10-02', 'valid_until': '2026-10-10'}, self.store)
        counts = (len(self.store.price_versions()), len(self.store.records('quote_snapshot')))
        dashboard = run({'action': 'dashboard'}, self.store)
        self.assertEqual(counts, (len(self.store.price_versions()), len(self.store.records('quote_snapshot'))))
        self.assertEqual(dashboard['summary']['issue_count'], 1)
        self.assertIn('有効期間外', dashboard['issues'][0]['issues'])
        self.assertEqual(dashboard['inventory'][0]['unit_price'], '120')

    def test_large_exact_total_is_rejected_without_saving_quote(self):
        price = '9' * 28
        run({'action': 'register', 'item': self.item(price), 'confirmed_by': '担当', 'reason': '確認'}, self.store)
        with self.assertRaises(ValidationError):
            run({'action': 'save_quote', 'quote_id': 'too-large', 'confirmed_by': '担当',
                 'lines': [{'item_id': 'paint-1', 'quantity': price, 'unit': 'ml', 'price_type': '販売'}]}, self.store)
        self.assertEqual(self.store.records('quote_snapshot', 'too-large'), [])

    def test_omitted_supplier_is_inferred_only_when_unambiguous(self):
        run({'action': 'register', 'item': self.item(), 'confirmed_by': '担当', 'reason': '確認',
             'supplier_id': 'supplier-a'}, self.store)
        run({'action': 'register', 'item': self.item('121'), 'confirmed_by': '担当', 'reason': '確認',
             'supplier_id': 'supplier-b'}, self.store)
        before = len(self.store.price_versions())
        with self.assertRaises(ValidationError):
            run({'action': 'update_price', 'item': self.item('122'), 'confirmed_by': '担当', 'reason': '更新'}, self.store)
        self.assertEqual(len(self.store.price_versions()), before)

    def test_quote_product_precision_and_append_are_atomic(self):
        # A second valid line must not be stored if the later line overflows.
        run({'action': 'register', 'item': self.item('9' * 28), 'confirmed_by': '担当', 'reason': '確認'}, self.store)
        with self.assertRaises(ValidationError):
            run({'action': 'save_quote', 'quote_id': 'atomic-quote', 'confirmed_by': '担当', 'lines': [
                {'item_id': 'paint-1', 'quantity': '1', 'unit': 'ml', 'price_type': '販売',
                 'quote_line_id': 'line-ok'},
                {'item_id': 'paint-1', 'quantity': '9' * 28, 'unit': 'ml', 'price_type': '販売',
                 'quote_line_id': 'line-overflow'},
            ]}, self.store)
        self.assertEqual(self.store.records('quote_snapshot', 'atomic-quote'), [])


if __name__ == '__main__':
    unittest.main()
