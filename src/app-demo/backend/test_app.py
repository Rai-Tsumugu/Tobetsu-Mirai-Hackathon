"""Checks real persistence, monetary boundaries, and candidate provenance."""
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import app as module


class SimulatorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = module.DB_PATH
        module.DB_PATH = Path(self.temp.name) / 'test.sqlite3'
        self.client = TestClient(module.app)
        self.client.__enter__()
        self.vehicle = self.client.get('/api/vehicles?query=FL4').json()[0]
        self.grade = self.vehicle['grades'][0]

    def tearDown(self):
        self.client.__exit__(None, None, None)
        module.DB_PATH = self.previous
        self.temp.cleanup()

    def body(self, **overrides):
        item = dict(job_id='brake', selected_source_ids=['brake-0', 'brake-1', 'brake-2'], labor_price=6000, parts_price=12000, conditions='前輪左右', adjustment_reason='')
        item.update(overrides)
        return dict(vehicle_id='FL4', year=2023, grade=self.grade, items=[item], notes='テスト見積もり')

    def test_search_and_explicit_variant(self):
        self.assertEqual(len(self.client.get('/api/vehicles?query=シビック').json()), 2)
        self.assertIsNone(self.client.get('/api/vehicles/FL4').json()['length_mm'])
        body = dict(vehicle_id='FL4', year=2100, grade=self.grade, job_ids=['brake'])
        self.assertEqual(self.client.post('/api/price-research', json=body).status_code, 422)
        body.update(year=2023, grade='未登録仕様')
        self.assertEqual(self.client.post('/api/price-research', json=body).status_code, 422)

    def test_candidates_deterministic_and_tax_normalized(self):
        body = dict(vehicle_id='FL4', year=2023, grade=self.grade, job_ids=['brake'])
        first = self.client.post('/api/price-research', json=body).json()
        self.assertEqual(first, self.client.post('/api/price-research', json=body).json())
        self.assertEqual(len(first['brake']), 4)
        self.assertEqual(first['brake'][1]['labor_price'], 6600)
        self.assertEqual(first['brake'][1]['normalized_labor'], 6000)
        self.assertIsNone(first['brake'][3]['normalized_labor'])
        self.assertTrue(all(s['source_url'] is None and s['mode'] == 'simulator' for s in first['brake']))
        body['mode'] = 'invalid'
        self.assertEqual(self.client.post('/api/price-research', json=body).status_code, 422)

    def test_save_reopen_and_relational_provenance(self):
        response = self.client.post('/api/estimates', json=self.body())
        self.assertEqual(response.status_code, 201, response.text)
        saved = response.json()
        self.assertEqual((saved['subtotal'], saved['tax_amount'], saved['total_amount']), (18000, 1800, 19800))
        self.assertEqual(saved['items'][0]['calculated_labor_price'], 6000)
        with TestClient(module.app) as second:
            self.assertEqual(second.get('/api/estimates/' + saved['id']).json(), saved)
            self.assertEqual(len(second.get('/api/estimates?query=2023').json()), 1)
            self.assertEqual(len(second.get('/api/estimates?query=ブレーキ').json()), 1)
        with module.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM price_sources').fetchone()[0], 4)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM selected_sources').fetchone()[0], 3)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_exclusions_even_median_and_zero_candidates(self):
        saved = self.client.post('/api/estimates', json=self.body(selected_source_ids=['brake-0', 'brake-2', 'brake-3'], labor_price=6500)).json()
        self.assertEqual(saved['items'][0]['calculated_labor_price'], 6500)
        invalid = self.client.post('/api/estimates', json=self.body(selected_source_ids=[]))
        self.assertEqual(invalid.status_code, 422)
        saved = self.client.post('/api/estimates', json=self.body(selected_source_ids=[], labor_price=7201, adjustment_reason='手入力')).json()
        self.assertIsNone(saved['items'][0]['calculated_labor_price'])
        self.assertEqual(saved['tax_amount'], 1920)

    def test_reject_tampering_and_invalid_money(self):
        for patch in [dict(labor_price=-1), dict(parts_price=1.5), dict(labor_price=True), dict(parts_price=10000001), dict(selected_source_ids=['oil-0']), dict(selected_source_ids=['brake-0', 'brake-0'])]:
            with self.subTest(patch=patch):
                self.assertEqual(self.client.post('/api/estimates', json=self.body(**patch)).status_code, 422)
        body = self.body()
        body['total_amount'] = 1
        self.assertEqual(self.client.post('/api/estimates', json=body).status_code, 422)
        self.assertEqual(self.client.post('/api/estimates', json=self.body(labor_price=9000)).status_code, 422)
        body = self.body()
        body['items'] *= 2
        self.assertEqual(self.client.post('/api/estimates', json=body).status_code, 422)

    def test_manual_registration_and_multiple_jobs(self):
        response = self.client.post('/api/vehicles', json=dict(maker='手入力メーカー', model='試験車', model_code='TEST', year=2020, grade='試験仕様'))
        self.assertEqual(response.status_code, 201)
        vehicle = response.json()
        self.assertEqual(vehicle['source_name'], 'manual')
        self.assertEqual(self.client.get('/api/vehicles/' + vehicle['id']).json(), vehicle)
        body = self.body()
        body.update(vehicle_id=vehicle['id'], year=2020, grade='試験仕様')
        body['items'].append(dict(job_id='oil', selected_source_ids=['oil-0'], labor_price=1000, parts_price=3501, conditions='フィルター別', adjustment_reason=''))
        saved = self.client.post('/api/estimates', json=body).json()
        self.assertEqual(saved['labor_total'], 7000)
        self.assertEqual(saved['tax_amount'], 2250)
        self.assertEqual(saved['total_amount'], 24751)


if __name__ == '__main__':
    unittest.main()
