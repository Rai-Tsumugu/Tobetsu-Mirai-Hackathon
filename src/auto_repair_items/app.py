"""Run with PYTHONPATH=src python3 -m auto_repair_items.app.

Local-only demonstration server; no external requests, credentials or uploads
to third parties. The design's React/FastAPI stack was a candidate: this
standalone stdlib implementation needs no dependency installation.
"""
import argparse
from decimal import Decimal, localcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from .core import Store, ValidationError, dumps, seed_demo
from .registry import module_for, specifications

MAX_BODY_BYTES = 4 * 1024 * 1024


def make_handler(database_path):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status, value):
            body = dumps(value).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ('/', '/ideas'):
                body = Path(__file__).with_name('workspace.html' if path == '/' else 'index.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)
            elif path == '/api/ideas':
                self.send_json(200, {'mode': 'simulator', 'ideas': specifications()})
            elif path == '/api/prices':
                store = Store(database_path)
                try:
                    self.send_json(200, {'mode': 'simulator', 'price_versions': store.price_versions()})
                finally:
                    store.close()
            else:
                self.send_json(404, {'error': 'ページがありません'})

        def do_POST(self):
            # Reject cross-origin browser writes to the local SQLite database.
            origin = self.headers.get('Origin')
            expected_origin = f'http://{self.headers.get("Host")}'
            allowed_hosts = (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')
            if self.headers.get('Host') not in allowed_hosts or (origin is not None and origin != expected_origin):
                self.send_json(403, {'error': '同じ画面から操作してください'})
                return
            path = urlsplit(self.path).path
            if path != '/api/workspace' and not path.startswith('/api/ideas/'):
                self.send_json(404, {'error': '操作がありません'})
                return
            store = None
            try:
                content_length = int(self.headers.get('Content-Length', '0'))
                if not 0 < content_length <= MAX_BODY_BYTES:
                    raise ValidationError('入力サイズを確認してください（最大4MB）')
                if not self.headers.get('Content-Type', '').startswith('application/json'):
                    raise ValidationError('JSON形式の入力が必要です')
                payload = json.loads(self.rfile.read(content_length), parse_float=Decimal,
                                     parse_constant=lambda value: _invalid_number(value))
                if not isinstance(payload, dict):
                    raise ValidationError('入力は項目の集合で指定してください')
                if path == '/api/workspace':
                    from . import integrated as module
                else:
                    module = module_for(path.rsplit('/', 1)[-1])
                store = Store(database_path)
                with store.transaction(), localcontext() as context:
                    context.prec = 120
                    result = module.run(payload, store)
                self.send_json(200, {'mode': 'simulator', 'idea_id': 'integrated' if path == '/api/workspace' else module.SPEC['idea_id'], 'result': result})
            except (ValueError, TypeError, KeyError, UnicodeError) as error:
                self.send_json(400, {'error': str(error), 'status': '要確認'})
            except ModuleNotFoundError:
                self.send_json(404, {'error': 'この案はまだ利用できません'})
            finally:
                if store is not None:
                    store.close()

        def log_message(self, format, *args):
            # Do not log input bodies, personal data or file contents.
            return

    return Handler


def _invalid_number(value):
    raise ValidationError('NaN / Infinity は使用できません')


def create_server(database_path, port=8765):
    store = Store(database_path)
    try:
        seed_demo(store)
    finally:
        store.close()
    return ThreadingHTTPServer(('127.0.0.1', port), make_handler(database_path))


def main():
    parser = argparse.ArgumentParser(description='部品・材料マスタ M01–M30 / 架空値Simulator')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--db', default=str(Path(tempfile.gettempdir()) / 'auto_repair_items.sqlite3'))
    args = parser.parse_args()
    server = create_server(args.db, args.port)
    print(f'Simulator（全数値は架空）: http://127.0.0.1:{server.server_port}', flush=True)
    print(f'SQLite: {args.db}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
