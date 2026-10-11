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
        self.assertNotIn('maximum', json.dumps(request.call_args_list[1].kwargs['json']['generationConfig']['responseJsonSchema']))
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

    def test_price_ranges_and_assumed_quantities_are_rejected(self):
        for evidence in ['料金4,800〜6,300円', '4.0Lと仮定し算出した部品代6,320円', '工賃の目安6,000円']:
            with self.subTest(evidence=evidence):
                result = {'data': {'sources': [price(evidence=evidence)]}, 'citations': [{'url': URL, 'title': '記事'}], 'warnings': []}
                self.assertEqual(gemini.extract_prices(result, ['brake'])['brake'], [])
                self.assertTrue(result['warnings'])

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

    def test_vehicle_ai_removed_and_winter_conditions_not_sent(self):
        with mock_google([]) as request:
            self.assertNotIn('/api/vehicle-research', [getattr(route, 'path', '') for route in module.app.routes])
            self.assertIn(self.client.post('/api/vehicle-research', json={'query': 'トヨタ'}).status_code, (404, 405))
            request.assert_not_called()
        result, request = self.post_research([price()])
        prompt = request.call_args_list[0].kwargs['json']['contents'][0]['parts'][0]['text']
        self.assertNotIn('冬', prompt)
        self.assertNotIn('融雪剤', prompt)
        self.assertNotIn('region', result['context'])
        self.assertNotIn('winter_conditions', result['context'])
        saved = self.client.post('/api/estimates', json=self.estimate(result))
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual(saved.json()['total_amount'], 19800)

    def test_transient_failure_retries_once_and_permanent_errors_are_explicit(self):
        with patch('gemini.time.sleep'), mock_google([httpx.Response(503), httpx.Response(200, json=grounded()), httpx.Response(200, json=extracted({'sources': [price()]}))]) as request:
            response = self.client.post('/api/price-research', json=self.context)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(request.call_count, 3)
        for status in [400, 404, 503]:
            gemini._last_request = 0
            with patch('gemini.time.sleep'), mock_google([httpx.Response(status), httpx.Response(status)]) as request:
                with self.assertRaises(Exception) as raised:
                    gemini.generate('test')
                self.assertIn(str(status), raised.exception.detail)
                self.assertEqual(request.call_count, 2 if status == 503 else 1)
        with mock_google([httpx.Response(400, json={'error': {'message': 'API key not valid. SECRET'}})]):
            with self.assertRaises(Exception) as raised:
                gemini.generate('test')
            self.assertIn('APIキー', raised.exception.detail)
            self.assertNotIn('SECRET', raised.exception.detail)

    def test_no_sources_no_invented_candidates(self):
        with mock_google([httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': '見つかりません'}]}}]})]) as request:
            result = self.client.post('/api/price-research', json=self.context).json()
        self.assertEqual(result['sources'], {'brake': []})
        self.assertEqual(request.call_count, 1)
        body = dict(mode='live', research_id=result['research_id'], vehicle_id='FL4', year=2023, grade=self.grade, items=[dict(job_id='brake', selected_source_ids=[], labor_price=7000, parts_price=0, conditions='', adjustment_reason='根拠不足のため手入力')])
        self.assertEqual(self.client.post('/api/estimates', json=body).status_code, 201)


if __name__ == '__main__':
    unittest.main()
