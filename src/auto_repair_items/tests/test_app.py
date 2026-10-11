import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from auto_repair_items.app import create_server


class AppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = create_server(Path(self.directory.name) / 'items.db', 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def test_page_and_contract(self):
        with urlopen(self.url) as response:
            self.assertIn('材料から見積、実績まで'.encode(), response.read())
        with urlopen(self.url + '/api/prices') as response:
            result = json.load(response)
        self.assertEqual(result['mode'], 'simulator')
        self.assertEqual(len(result['price_versions']), 2)
        self.assertEqual(result['price_versions'][0]['item']['unit_price'], '80')

    def test_integrated_http_workflow(self):
        def post(payload):
            request = Request(self.url + '/api/workspace',
                data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
            with urlopen(request) as response:
                return json.load(response)['result']
        dashboard = post({'action': 'dashboard', 'as_of': '2026-10-11'})
        self.assertIsInstance(dashboard, dict)
        quote = post({'action': 'save_quote', 'quote_id': 'http-quote',
            'as_of': '2026-10-11', 'confirmed_by': 'テスト担当',
            'lines': [{'item_id': 'demo-paint', 'quantity': '2', 'unit': 'ml', 'price_type': '販売'}]})
        self.assertEqual(quote['quote']['subtotal'], '240')
        saved = post({'action': 'get_quote', 'quote_id': 'http-quote'})
        self.assertEqual(saved['quote']['lines'], quote['quote']['lines'])
        with urlopen(self.url + '/ideas') as response:
            self.assertIn('材料'.encode(), response.read())

    def test_input_and_cross_origin_errors(self):
        cases = [(b'[]', {}, 400), (b'{"value":NaN}', {}, 400),
                 (b'{}', {'Origin': 'https://unrelated.example'}, 403),
                 (b'{}', {'Host': 'unrelated.example', 'Origin': 'http://unrelated.example'}, 403)]
        for body, headers, status in cases:
            request = Request(self.url + '/api/ideas/M07', data=body,
                headers={'Content-Type': 'application/json', **headers})
            with self.subTest(body=body), self.assertRaises(HTTPError) as caught:
                urlopen(request)
            self.assertEqual(caught.exception.code, status)
            caught.exception.close()


if __name__ == '__main__':
    unittest.main()
