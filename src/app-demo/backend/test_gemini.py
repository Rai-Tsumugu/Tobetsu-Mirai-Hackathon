import json
from contextlib import contextmanager
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
import app as module
import gemini

URL = 'https://example.org/workshop/brake'

def grounded():
    return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '根拠のある調査結果'}]}, 'groundingMetadata': {'groundingChunks': [{'web': {'uri': URL, 'title': '整備記事'}}], 'searchEntryPoint': {'renderedContent': '<p>検索候補</p>'}}}]}


def price(**changes):
    record = dict(job_id='brake', source_url=URL, labor_price=6600, parts_price=12000, total_price=None, tax_included=True, tax_rate=0.1, vehicle_match='exact', work_matches=True, work_conditions='前輪左右', published_at=None, evidence='工賃6,600円（税込）')
    record.update(changes)
    return record


def extracted(data):
    return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(data, ensure_ascii=False)}]}}]}


@contextmanager
def mock_google(responses):
    # Replace the outbound client factory, not TestClient's inherited post method.
    with patch('gemini.httpx.Client') as factory:
        post = factory.return_value.__enter__.return_value.post
        post.side_effect = responses
        yield post


class GeminiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = module.DB_PATH
        module.DB_PATH = Path(self.temp.name) / 'test.sqlite3'
        gemini._last_request = 0
        self.env = patch.dict(os.environ, {'GEMINI_API_KEY': 'test-placeholder'})
        self.env.start()
        self.client = TestClient(module.app)
        self.client.__enter__()
        self.grade = self.client.get('/api/vehicles/FL4').json()['grades'][0]
        self.context = dict(vehicle_id='FL4', year=2023, grade=self.grade, job_ids=['brake'], mode='live')

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        module.DB_PATH = self.db
        gemini._last_request = 0
        self.temp.cleanup()

    def post_research(self, records):
        with mock_google([httpx.Response(200, json=grounded()), httpx.Response(200, json=extracted({'sources': records}))]) as request:
            response = self.client.post('/api/price-research', json=self.context)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), request

    def estimate(self, result, **changes):
        source = result['sources']['brake'][0]
        body = dict(mode='live', research_id=result['research_id'], vehicle_id='FL4', year=2023, grade=self.grade, items=[dict(job_id='brake', selected_source_ids=[source['id']], labor_price=6000, parts_price=12000, conditions='前輪左右', adjustment_reason='')], notes='')
        body.update(changes)
        return body

    def test_free_model_request_cache_and_persistence(self):
        result, request = self.post_research([price()])
        self.assertEqual(request.call_count, 2)
        first = request.call_args_list[0]
        self.assertIn('gemini-2.5-flash:generateContent', first.args[0])
        self.assertEqual(first.kwargs['json']['tools'], [{'google_search': {}}, {'url_context': {}}])
        self.assertEqual(result['sources']['brake'][0]['normalized_labor'], 6000)
        self.assertFalse(result['sources']['brake'][0]['verified'])
        with mock_google([]) as request:
            cached = self.client.post('/api/price-research', json=self.context).json()
        self.assertTrue(cached['cached'])
        request.assert_not_called()
        self.assertEqual(cached['research_id'], result['research_id'])
        saved = self.client.post('/api/estimates', json=self.estimate(result))
        self.assertEqual(saved.status_code, 201, saved.text)
        saved = saved.json()
        self.assertEqual(saved['mode'], 'live')
        self.assertEqual(saved['total_amount'], 19800)
        self.assertEqual(saved['items'][0]['sources'][0]['source_url'], URL)
        self.assertEqual(self.client.get('/api/estimates/' + saved['id']).json(), saved)
        with module.connect() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(self.client.post('/api/estimates', json=self.estimate(result, year=2024)).status_code, 422)
        self.assertEqual(self.client.post('/api/estimates', json=self.estimate(result, research_id='forged')).status_code, 422)

    def test_unknown_tax_total_only_and_mismatch_not_compared(self):
        for changes in [dict(tax_included=None), dict(tax_rate=None), dict(labor_price=None, total_price=19800), dict(vehicle_match='similar'), dict(work_matches=None)]:
            with self.subTest(changes=changes):
                result = {'data': {'sources': [price(**changes)]}, 'citations': [{'url': URL, 'title': '整備記事'}], 'warnings': []}
                sources = gemini.extract_prices(result, ['brake'])
                self.assertIsNone(sources['brake'][0]['normalized_labor'])

    def test_fabricated_source_duplicate_wrong_job_and_bad_money(self):
        result = {'data': {'sources': [price(), price(), price(source_url='https://invented.example/a'), price(job_id='oil')]}, 'citations': [{'url': URL, 'title': '記事'}], 'warnings': []}
        self.assertEqual(len(gemini.extract_prices(result, ['brake'])['brake']), 1)
        result['data']['sources'] = [price(labor_price=-1)]
        with self.assertRaises(Exception) as raised:
            gemini.extract_prices(result, ['brake'])
        self.assertEqual(raised.exception.status_code, 502)
        for url in ['http://example.org', 'https://127.0.0.1/', 'https://localhost/', 'https://user:pass@example.org/', 'https://[::1]/']:
            self.assertFalse(gemini.public_url(url))

    def test_missing_key_quota_and_malformed_response(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            response = self.client.post('/api/price-research', json=self.context)
            self.assertEqual(response.status_code, 503)
            self.assertFalse(self.client.get('/api/config').json()['gemini_configured'])
        with mock_google([httpx.Response(429)]) as request:
            self.assertEqual(self.client.post('/api/price-research', json=self.context).status_code, 429)
            self.assertEqual(request.call_count, 1)
        gemini._last_request = 0
        with mock_google([httpx.Response(200, json={'candidates': []})]):
            self.assertEqual(self.client.post('/api/price-research', json=self.context).status_code, 502)
        with mock_google([]) as request:
            self.assertEqual(self.client.post('/api/price-research', json=self.context).status_code, 429)
            request.assert_not_called()

    def test_vehicle_search_registers_attributed_data_and_unknowns(self):
        vehicle = dict(maker='トヨタ', model='試験車', model_code='TEST-1', years=[2020], grades=['試験仕様'], length_mm=4000, width_mm=None, height_mm=None, powertrain=None, source_url=URL, evidence='TEST-1 2020年 試験仕様')
        with mock_google([httpx.Response(200, json=grounded()), httpx.Response(200, json=extracted({'vehicles': [vehicle]}))]):
            result = self.client.post('/api/vehicle-research', json={'query': 'トヨタ'}).json()
        self.assertEqual(len(result['values']), 1)
        saved = result['values'][0]
        self.assertEqual(saved['source_name'], 'gemini_web')
        self.assertIsNone(saved['verified_at'])
        self.assertIsNone(saved['width_mm'])
        self.assertEqual(self.client.get('/api/vehicles/' + saved['id']).json(), saved)
        self.assertEqual(len(self.client.get('/api/vehicles?origin=live&query=トヨタ').json()), 1)
        vehicle['years'] = []
        result = {'data': {'vehicles': [vehicle]}, 'citations': [{'url': URL, 'title': '記事'}], 'warnings': []}
        self.assertEqual(gemini.extract_vehicles(result), [])

    def test_no_sources_no_invented_candidates(self):
        with mock_google([httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': '見つかりません'}]}}]})]) as request:
            result = self.client.post('/api/price-research', json=self.context).json()
        self.assertEqual(result['sources'], {'brake': []})
        self.assertEqual(request.call_count, 1)
        body = dict(mode='live', research_id=result['research_id'], vehicle_id='FL4', year=2023, grade=self.grade, items=[dict(job_id='brake', selected_source_ids=[], labor_price=7000, parts_price=0, conditions='', adjustment_reason='根拠不足のため手入力')])
        self.assertEqual(self.client.post('/api/estimates', json=body).status_code, 201)


if __name__ == '__main__':
    unittest.main()
