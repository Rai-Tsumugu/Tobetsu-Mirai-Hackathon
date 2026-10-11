"""Case identity, persistence, migration, and atomic quote linkage."""
import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import app as module


class CaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = module.DB_PATH
        module.DB_PATH = Path(self.temp.name) / 'cases.sqlite3'
        self.client = TestClient(module.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        module.DB_PATH = self.previous
        self.temp.cleanup()

    def quote(self, case_id=None):
        grade = self.client.get('/api/vehicles/FL4').json()['grades'][0]
        return dict(case_id=case_id, vehicle_id='FL4', year=2023, grade=grade,
                    items=[dict(job_id='oil', selected_source_ids=['oil-0'], labor_price=1000,
                                parts_price=5000, conditions='検証', adjustment_reason='')])

    def test_unique_ids_and_restart_persistence(self):
        first = self.client.post('/api/cases', json={'title': '同じ案件名'}).json()
        second = self.client.post('/api/cases', json={'title': '同じ案件名'}).json()
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(first['status'], 'unestimated')
        self.assertIsNone(first['amount'])
        self.assertIsNone(first['due_date'])
        with TestClient(module.app) as restarted:
            self.assertEqual({c['id'] for c in restarted.get('/api/cases').json()}, {first['id'], second['id']})

    def test_edit_keeps_identity_and_dates(self):
        case = self.client.post('/api/cases', json={'title': 'オイル交換'}).json()
        fields = dict(title='更新案件', vehicle_label='FL4', status='estimating', amount=0,
                      due_date='2026-10-20', notes='部品待ち')
        result = self.client.put('/api/cases/' + case['id'], json=fields)
        self.assertEqual(result.status_code, 200)
        updated = result.json()
        self.assertEqual(updated['id'], case['id'])
        self.assertEqual(updated['created_at'], case['created_at'])
        for field, value in fields.items():
            self.assertEqual(updated[field], value)
        fields.update(amount=None, due_date=None, status='completed')
        updated = self.client.put('/api/cases/' + case['id'], json=fields).json()
        self.assertIsNone(updated['amount'])
        self.assertIsNone(updated['due_date'])

    def test_reject_invalid_case_data_and_missing_case(self):
        for patch in [dict(title=' '), dict(status='other'), dict(amount=-1), dict(amount=1.5),
                      dict(amount=True), dict(amount=110000001), dict(due_date='2026-02-30'),
                      dict(id='pretend'), dict(latest_estimate_id='pretend')]:
            with self.subTest(patch=patch):
                self.assertEqual(self.client.post('/api/cases', json={'title': '試験', **patch}).status_code, 422)
        self.assertEqual(self.client.put('/api/cases/missing', json={'title': '更新'}).status_code, 404)
        self.assertEqual(self.client.get('/api/cases').json(), [])

    def test_quote_completes_only_linked_case_with_actual_total(self):
        case = self.client.post('/api/cases', json=dict(title='受付案件', amount=9000, due_date='2026-10-20', notes='受付メモ')).json()
        other = self.client.post('/api/cases', json=dict(title='別案件')).json()
        response = self.client.post('/api/estimates', json=self.quote(case['id']))
        self.assertEqual(response.status_code, 201, response.text)
        saved = response.json()
        self.assertEqual(saved['case_id'], case['id'])
        cases = {c['id']: c for c in self.client.get('/api/cases').json()}
        linked = cases[case['id']]
        self.assertEqual((linked['status'], linked['amount'], linked['latest_estimate_id']), ('completed', 6600, saved['id']))
        self.assertEqual((linked['due_date'], linked['notes'], linked['title']), ('2026-10-20', '受付メモ', '受付案件'))
        self.assertEqual(cases[other['id']], other)
        revision = self.client.post('/api/estimates', json=self.quote(case['id'])).json()
        linked = next(c for c in self.client.get('/api/cases').json() if c['id'] == case['id'])
        self.assertEqual(linked['latest_estimate_id'], revision['id'])
        self.assertEqual(len(self.client.get('/api/estimates').json()), 2)

    def test_bad_link_rolls_back_entire_save(self):
        response = self.client.post('/api/estimates', json=self.quote('missing'))
        self.assertEqual(response.status_code, 404)
        with module.connect() as db:
            for table in ['cases', 'estimates', 'estimate_items', 'price_sources']:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)

    def test_legacy_client_gets_case_and_invalid_quote_creates_none(self):
        invalid = self.quote()
        invalid['items'][0]['labor_price'] = -1
        self.assertEqual(self.client.post('/api/estimates', json=invalid).status_code, 422)
        self.assertEqual(self.client.get('/api/cases').json(), [])
        saved = self.client.post('/api/estimates', json=self.quote()).json()
        cases = self.client.get('/api/cases').json()
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]['id'], saved['case_id'])
        self.assertEqual(cases[0]['amount'], saved['total_amount'])

    def test_migration_is_idempotent_preserves_quote(self):
        saved = self.client.post('/api/estimates', json=self.quote()).json()
        old_case_id = saved.pop('case_id')
        with module.connect() as db:
            db.execute('UPDATE estimates SET data=? WHERE id=?', (json.dumps(saved), saved['id']))
            db.execute('DELETE FROM cases WHERE id=?', (old_case_id,))
        module.initialize()
        cases = self.client.get('/api/cases').json()
        self.assertEqual(len(cases), 1)
        migrated = self.client.get('/api/estimates/' + saved['id']).json()
        self.assertEqual(migrated.pop('case_id'), cases[0]['id'])
        self.assertEqual(migrated, saved)
        module.initialize()
        self.assertEqual(self.client.get('/api/cases').json(), cases)
        with module.connect() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])


if __name__ == '__main__':
    unittest.main()
