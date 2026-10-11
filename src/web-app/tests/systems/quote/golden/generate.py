"""Record golden input/output pairs from the original Python quote system.

Run from the repository root (any Python 3.11+ with fastapi/httpx installed):

    python src/web-app/tests/systems/quote/golden/generate.py

It imports ``src.auto_repair_quote`` unchanged, runs its own unittest suite
(``test_*.py`` and ``tests/``) plus a few extra API scenarios defined below,
and records every top-level call the tests make into the 30 ideas, the
pipeline/workflow, the SQLite store and the HTTP API. Each record holds the
arguments, the store state before/after, and the result or the exception.
The TypeScript port replays the same records (tests/systems/quote/golden.test.ts).

Clock, today and uuid4 are replaced with deterministic fakes so the outputs are
reproducible. Nothing in src/auto_repair_quote is modified or written to.
"""
from __future__ import annotations

import datetime as dt
import decimal
import functools
import importlib
import inspect
import json
import math
import os
import sys
import unittest
import uuid as uuidmod
from collections import defaultdict
from pathlib import Path

if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    os.execv(sys.executable, [sys.executable] + sys.argv)
os.environ['AUTO_REPAIR_QUOTE_DB'] = ':memory:'

ROOT = Path(__file__).resolve().parents[6]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
PKG = 'src.auto_repair_quote'
PKG_DIR = ROOT / 'src' / 'auto_repair_quote'

NAMES = ['common', 'fixtures', 'pipeline', 'workflow', 'store'] + [f'p{i:02d}' for i in range(1, 31)] + ['api']
MODS = {name: importlib.import_module(f'{PKG}.{name}') for name in NAMES}
QuoteStore = MODS['store'].QuoteStore

# ---- deterministic clock / today / uuid4 ----
FIXED_NOW = dt.datetime(2026, 10, 11, 3, 4, 5, 123456, tzinfo=dt.timezone.utc)


class FakeDatetime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW if tz is not None else FIXED_NOW.replace(tzinfo=None)


class FakeDate(dt.date):
    @classmethod
    def today(cls):
        return dt.date(2026, 10, 11)


SEQ = [0]


def fake_uuid4():
    SEQ[0] += 1
    return uuidmod.UUID(hex=f'{SEQ[0]:08x}' + '0' * 24)


for module in MODS.values():
    if getattr(module, 'datetime', None) is dt.datetime:
        module.datetime = FakeDatetime
    if getattr(module, 'date', None) is dt.date:
        module.date = FakeDate
    if getattr(module, 'uuid4', None) is uuidmod.uuid4:
        module.uuid4 = fake_uuid4

# ---- value encoding ----


class Skip(Exception):
    pass


def enc(value, ctx=None):
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {'__float__': 'nan' if math.isnan(value) else ('inf' if value > 0 else '-inf')}
    if isinstance(value, decimal.Decimal):
        return {'__decimal__': str(value)}
    if type(value) is dict:
        if not all(isinstance(key, str) for key in value):
            raise Skip('non-string key')
        return {key: enc(item, ctx) for key, item in value.items()}
    if type(value) is list:
        return [enc(item, ctx) for item in value]
    if ctx is not None and isinstance(value, QuoteStore):
        ctx['store'] = value
        return {'__store__': True}
    if ctx is not None and callable(value):
        if getattr(value, '__wrapped__', None) is ORIGINALS.get('pipeline.calculate'):
            return {'__callable__': 'pipeline.calculate'}
        recorder = CallableRecorder(value)
        ctx.setdefault('callables', []).append(recorder)
        return recorder
    raise Skip(type(value).__name__)


class CallableRecorder:
    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    def __call__(self, *args, **kwargs):
        result = self.fn(*args, **kwargs)
        self.calls.append({'args': enc(list(args)), 'result': enc(result)})
        return result


def finalize(value):
    if isinstance(value, CallableRecorder):
        return {'__callable__': 'recorded', 'calls': value.calls}
    if isinstance(value, list):
        return [finalize(item) for item in value]
    if isinstance(value, dict):
        return {key: finalize(item) for key, item in value.items()}
    return value


def error_record(error):
    names = [cls.__name__ for cls in type(error).__mro__]
    if 'IntegrityError' in names:
        kind = 'IntegrityError'
    elif 'KeyError' in names:
        kind = 'KeyError'
    elif 'ValueError' in names or 'InvalidOperation' in names:
        kind = 'ValueError'
    elif 'TypeError' in names or 'AttributeError' in names:
        kind = 'TypeError'
    else:
        kind = type(error).__name__
    return {'kind': kind, 'type': type(error).__name__, 'message': str(error)}


def dump(store):
    con = store.connection

    def rows(sql):
        return [list(row) for row in con.execute(sql)]

    return {
        'quote_versions': [[enc(r[0]), enc(r[1]), enc(r[2]), enc(r[3]), enc(r[4]), json.loads(r[5])]
                           for r in rows('SELECT quote_id, quote_version, customer_ref, vehicle_ref, job_ref, snapshot FROM quote_versions ORDER BY rowid')],
        'communications': [[enc(r[0]), enc(r[1]), enc(r[2]), json.loads(r[3])]
                           for r in rows('SELECT communication_id, quote_id, quote_version, snapshot FROM communications ORDER BY rowid')],
        'change_events': [[enc(r[0]), enc(r[1]), enc(r[2]), json.loads(r[3])]
                          for r in rows('SELECT event_id, quote_id, quote_version, snapshot FROM change_events ORDER BY rowid')],
        'drafts': [[enc(r[0]), json.loads(r[1])] for r in rows('SELECT draft_id, snapshot FROM drafts ORDER BY rowid')],
        'price_history': [[r[0], enc(r[1]), json.loads(r[2])]
                          for r in rows('SELECT history_id, item_id, snapshot FROM price_history ORDER BY history_id')],
    }


# ---- recording wrappers ----
DEPTH = [0]
CURRENT_TEST = ['']
RECORDS = defaultdict(list)
ORIGINALS = {}


def wrap(group, name, fn):
    signature = inspect.signature(fn)
    key = f'{group}.{name}'
    ORIGINALS[key] = fn

    @functools.wraps(fn)
    def recorded(*args, **kwargs):
        if DEPTH[0] > 0:
            DEPTH[0] += 1
            try:
                return fn(*args, **kwargs)
            finally:
                DEPTH[0] -= 1
        record = None
        ctx = {}
        try:
            bound = signature.bind(*args, **kwargs)
            positional, kwonly = [], {}
            params = list(signature.parameters.values())
            supplied = bound.arguments
            last = max([i for i, p in enumerate(params) if p.name in supplied] + [-1])
            for index, param in enumerate(params):
                if param.kind is param.VAR_POSITIONAL:
                    positional.extend(enc(item, ctx) for item in supplied.get(param.name, ()))
                elif param.kind is param.KEYWORD_ONLY:
                    if param.name in supplied:
                        kwonly[param.name] = enc(supplied[param.name], ctx)
                elif param.kind is param.VAR_KEYWORD:
                    for k, v in supplied.get(param.name, {}).items():
                        kwonly[k] = enc(v, ctx)
                elif index <= last:
                    if param.name in supplied:
                        positional.append(enc(supplied[param.name], ctx))
                    else:
                        positional.append(enc(param.default, ctx))
            record = {'test': CURRENT_TEST[0], 'fn': key, 'args': positional, 'uuid_seq': SEQ[0]}
            if kwonly:
                record['kwargs'] = kwonly
            if 'store' in ctx:
                record['store_before'] = dump(ctx['store'])
        except (Skip, TypeError):
            record = None
        DEPTH[0] = 1
        try:
            result = fn(*args, **kwargs)
        except BaseException as error:
            if record is not None:
                record['error'] = error_record(error)
            raise
        else:
            if record is not None:
                try:
                    record['result'] = enc(result)
                except Skip:
                    record = None
            return result
        finally:
            DEPTH[0] = 0
            if record is not None:
                if 'store' in ctx:
                    record['store_after'] = dump(ctx['store'])
                record['args'] = finalize(record['args'])
                if 'kwargs' in record:
                    record['kwargs'] = finalize(record['kwargs'])
                RECORDS[group].append(record)

    return recorded


PUBLIC = {
    'common': ['number', 'range_value', 'money_range', 'add_ranges', 'multiply_ranges', 'new_quote', 'make_line'],
    'fixtures': ['demo_inputs', 'demo_presets'],
    'pipeline': ['calculate', 'json_ready'],
    'workflow': ['preview', 'saved_workflow'],
    'p01': ['apply'], 'p02': ['apply', 'calculate_billable_person_hours'],
    'p03': ['validate_inputs', 'apply'], 'p04': ['selling_price', 'apply'], 'p05': ['apply'],
    'p06': ['apply'], 'p07': ['apply', 'group_lines'], 'p08': ['band_cards', 'apply'],
    'p09': ['apply', 'tax_summary'], 'p10': ['source_badges', 'apply'],
    'p11': ['conditions_panel', 'apply'], 'p12': ['customer_summary', 'apply'],
    'p13': ['validate_step', 'advance_step', 'form_state'], 'p14': ['confirm_quote'],
    'p15': ['revise_quote', 'save_version'], 'p16': ['quick_quote'],
    'p17': ['save_draft', 'resume_draft', 'list_drafts'], 'p18': ['record_communication'],
    'p19': ['load_preset'], 'p20': ['search_jobs', 'select_job'],
    'p21': ['search_quotes', 'reoffer_quote'], 'p22': ['question_guide', 'answers_to_inputs'],
    'p23': ['compare_bands'], 'p24': ['price_comparison', 'save_price_history', 'compare_item_prices'],
    'p25': ['combine_quotes'], 'p26': ['compare_versions'], 'p27': ['save_snapshot', 'load_snapshot'],
    'p28': ['communication_ledger', 'append_communication', 'query_communications'],
    'p29': ['record_change', 'list_change_events'], 'p30': ['document_payload'],
}
for group, names in PUBLIC.items():
    module = MODS[group]
    for name in names:
        setattr(module, name, wrap(group, name, getattr(module, name)))

STORE_METHODS = ['save_quote', 'get_quote', 'list_quotes', 'append_communication', 'list_communications',
                 'append_change_event', 'list_change_events', 'save_draft', 'get_draft', 'list_drafts',
                 'save_price', 'list_prices']
for name in STORE_METHODS:
    setattr(QuoteStore, name, wrap('store', name, getattr(QuoteStore, name)))

from fastapi.testclient import TestClient  # noqa: E402

_original_request = TestClient.request


def recorded_request(self, method, url, *args, **kwargs):
    if DEPTH[0] > 0:
        return _original_request(self, method, url, *args, **kwargs)
    api = MODS['api']
    record = {'test': CURRENT_TEST[0], 'method': method.upper(), 'url': str(url), 'uuid_seq': SEQ[0],
              'store_before': dump(api.store)}
    if 'json' in kwargs:
        record['body'] = enc(kwargs['json'])
    DEPTH[0] = 1
    try:
        response = _original_request(self, method, url, *args, **kwargs)
    finally:
        DEPTH[0] = 0
    record['status'] = response.status_code
    try:
        record['response'] = response.json()
    except ValueError:
        record['response_text'] = response.text
    record['store_after'] = dump(api.store)
    RECORDS['api'].append(record)
    return response


TestClient.request = recorded_request


# ---- extra API scenarios (UI flows not covered by the original tests) ----
class ExtraScenarioTests(unittest.TestCase):
    def setUp(self):
        api = MODS['api']
        self.original_store = api.store
        api.store = QuoteStore()
        self.client = TestClient(api.app)

    def tearDown(self):
        api = MODS['api']
        self.client.close()
        api.store.close()
        api.store = self.original_store

    def test_ui_flow_with_discount_minimum_and_tools(self):
        c = self.client
        c.get('/api/teams')
        c.get('/api/jobs')
        c.get('/api/jobs?query=ブレーキ')
        c.get('/api/jobs?query=ＰＡＤ')
        c.get('/api/jobs?query=該当なし')
        loaded = c.post('/api/presets/load', json={'preset_id': 'PRESET-DEMO-01'}).json()
        c.post('/api/presets/load', json={'preset_id': 'missing'})
        inputs = c.get('/api/demo').json()
        for step in range(5):
            c.post('/api/forms/state', json={'inputs': inputs, 'step': step})
        c.post('/api/forms/state', json={'inputs': inputs, 'step': 7})
        discount = dict(inputs, discount={'scope': 'subtotal', 'line_ids': [], 'kind': 'rate', 'value': 0.1,
                                          'reason': '架空: デモ割引', 'approved_by': 'operator-demo-01', 'order': 'before_tax'})
        both = dict(discount, minimum_rule={'scope': 'labor', 'amount': 10000, 'effective_from': '2026-10-01',
                                            'approved_by': 'operator-demo-01', 'reason': '架空: 最低工賃のデモ'})
        minimum = dict(inputs, minimum_rule=both['minimum_rule'])
        for variant in (discount, both, dict(inputs, vehicle_ref='')):
            c.post('/api/workflow/preview', json={'inputs': variant})
        c.post('/api/quotes/calculate', json=discount)
        # The UI's discount checkbox makes preview fail in the original (P23 rejects the
        # negative discount line), so the saved flow below uses the minimum-charge rule.
        both = minimum
        preview = c.post('/api/workflow/preview', json={'inputs': both}).json()
        quote = preview['quote']
        c.post('/api/forms/state', json={'inputs': both, 'step': 4, 'quote': dict(quote, selected_band='low', confirmed_by='operator-demo-01')})
        c.post('/api/quotes/summary', json={'quote': quote, 'selected_band': 'high'})
        c.post('/api/quotes/summary', json={'quote': quote})
        c.post('/api/quotes/compare-bands', json={'quote': quote})
        c.post('/api/questions', json={'inputs': both})
        c.post('/api/questions', json={'inputs': {}, 'required_fields': ['vehicle_ref', 'labor.person_hours.low']})
        c.post('/api/prices/compare', json={'history': both['items'], 'item_id': both['items'][0]['item_id']})
        confirmed = c.post('/api/quotes/confirm', json={'inputs': both, 'quote_id': quote['quote_id'], 'quote_version': 1,
                                                        'selected_band': 'low', 'confirmed_by': 'operator-demo-01',
                                                        'final_amount': None, 'override_reason': ''}).json()
        c.post('/api/quotes/confirm', json={'inputs': both, 'quote_id': quote['quote_id'], 'quote_version': 1,
                                            'selected_band': 'low', 'confirmed_by': 'operator-demo-01'})
        qid = quote['quote_id']
        c.get(f'/api/workflow/{qid}?quote_version=1')
        c.get(f'/api/workflow/{qid}?quote_version=abc')
        c.get(f'/api/workflow/{qid}?quote_version=9')
        c.get(f'/api/quotes/{qid}/document?quote_version=1')
        c.get(f'/api/quotes/{qid}')
        c.get('/api/quotes/missing')
        c.get('/api/quotes/summary')
        c.post('/api/communications', json={'quote_id': qid, 'quote_version': 1, 'selected_band': 'low',
                                            'condition_note': '架空: 追加作業があれば再連絡', 'operator': 'operator-demo-01',
                                            'customer_ref': 'C-DEMO-01', 'vehicle_ref': 'V-DEMO-01', 'inputs': both})
        c.get(f'/api/quotes/{qid}/communications')
        changed = json.loads(json.dumps(both))
        changed['labor']['person_hours']['high'] = 3
        changed['labor']['breakdown'][0]['hours']['high'] = 3
        changed.update(quote_id=qid, quote_version=2, parent_version=1)
        p2 = c.post('/api/workflow/preview', json={'inputs': changed}).json()
        c.post('/api/quotes/diff', json={'from_quote': confirmed, 'to_quote': p2['quote']})
        c.post('/api/changes', json={'quote_id': qid, 'from_version': 1, 'to_version': 2, 'inputs': changed,
                                     'trigger_ref': 'OBS-DEMO-01', 'operator': 'operator-demo-01',
                                     'condition_note': '架空: 追加条件の説明を確認中', 'ack_status': 'pending'})
        c.post('/api/communications', json={'quote_id': qid, 'quote_version': 2, 'selected_band': 'high',
                                            'condition_note': '架空: 追加条件の説明', 'operator': 'operator-demo-01',
                                            'customer_ref': 'C-DEMO-01', 'vehicle_ref': 'V-DEMO-01', 'inputs': changed})
        ledger = c.get(f'/api/quotes/{qid}/communications').json()
        last = [r for r in ledger if r['quote_version'] == 2][-1]
        c.post('/api/changes', json={'quote_id': qid, 'from_version': 1, 'to_version': 2, 'inputs': changed,
                                     'trigger_ref': 'OBS-DEMO-01', 'operator': 'operator-demo-01',
                                     'condition_note': last['condition_note'], 'communicated_amount': last['communicated_amount'],
                                     'communication_id': last['communication_id'], 'ack_status': 'accepted'})
        c.get(f'/api/quotes/{qid}/changes')
        c.post('/api/quotes/confirm', json={'inputs': changed, 'quote_id': qid, 'quote_version': 2,
                                            'selected_band': 'high', 'confirmed_by': 'operator-demo-02',
                                            'final_amount': 30000, 'override_reason': '架空: 端数調整'})
        c.get(f'/api/workflow/{qid}')
        c.get('/api/quotes')
        c.get('/api/quotes?vehicle_ref=V-DEMO-01')
        c.get('/api/quotes?customer_ref=C-none')
        other = c.post('/api/quotes/calculate', json=dict(inputs, quote_id='Q-OTHER-1')).json()
        c.post('/api/quotes/combine', json={'quotes': [confirmed, other]})
        c.post('/api/quotes/revise', json={'quote_id': qid, 'from_version': 1, 'inputs': both})
        c.post('/api/drafts/save', json={'draft_id': 'D-DEMO-01', 'inputs': loaded, 'step': 1})
        c.post('/api/drafts/resume', json={'draft_id': 'D-DEMO-01', 'resume_mode': 'current'})
        c.post('/api/drafts/resume', json={'draft_id': 'D-DEMO-01', 'resume_mode': 'auto'})
        c.post('/api/drafts/resume', json={'draft_id': 'D-none', 'resume_mode': 'snapshot'})
        c.post('/api/quotes/quick', json={'preset_id': 'PRESET-DEMO-01', 'vehicle_ref': 'V-OTHER-9'})
        c.post('/api/workflow/preview', json={})
        c.post('/api/workflow/preview', json={'inputs': 'x'})
        c.post('/api/workflow/preview', json=[1])
        c.post('/api/quotes/confirm', json={'inputs': inputs})
        c.get('/api/nothing-here')
        c.post('/api/demo', json={})


# ---- run ----
class RecordingResult(unittest.TextTestResult):
    def startTest(self, test):
        CURRENT_TEST[0] = test.id().replace(PKG + '.', '')
        super().startTest(test)


def main():
    suite = unittest.TestSuite()
    for path in sorted(PKG_DIR.rglob('test_*.py')):
        if any(part in {'.venv', 'node_modules', '__pycache__'} for part in path.parts):
            continue
        relative = path.relative_to(PKG_DIR).with_suffix('')
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(PKG + '.' + '.'.join(relative.parts)))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ExtraScenarioTests))
    result = unittest.TextTestRunner(verbosity=0, resultclass=RecordingResult, stream=open(os.devnull, 'w')).run(suite)

    summary = {'tests_run': result.testsRun, 'tests_failed_under_recording': len(result.failures) + len(result.errors), 'records': {}}
    for path in OUT.glob('*.json'):
        path.unlink()
    for group, records in sorted(RECORDS.items()):
        seen, unique = set(), []
        for record in records:
            key = json.dumps({k: v for k, v in record.items() if k != 'test'}, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                unique.append(record)
        summary['records'][group] = len(unique)
        (OUT / f'{group}.json').write_text(json.dumps(unique, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for test, trace in result.failures + result.errors:
        print('FAILED UNDER RECORDING:', test.id(), trace.strip().splitlines()[-1])


if __name__ == '__main__':
    main()
