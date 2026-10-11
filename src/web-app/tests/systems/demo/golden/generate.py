"""整備見積デモ（src/app-demo/backend）のゴールデンを作る。元のコードを import して出力するだけで、元のファイルは変更しない。

実行方法（リポジトリのルートから。fastapi・httpx・python-dotenv が入った Python で）:
    python src/web-app/tests/systems/demo/golden/generate.py

出力:
    api.json   API のシナリオ（リクエスト・Gemini の模擬応答・期待するステータスと応答）。一時 SQLite で元のアプリを動かして作る。
    pure.json  DB を使わない関数（Simulator の候補、public_url、extract_prices、スキーマ、キャッシュキー、中央値）の入出力。
ID と時刻は実行ごとに変わるので、両方の言語で同じ規則（normalize）で置き換えてから比べる。
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from statistics import median
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[4] / 'app-demo' / 'backend'
sys.path.insert(0, str(BACKEND))
os.environ['GEMINI_API_KEY'] = 'test-placeholder'

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import app as module  # noqa: E402
import gemini  # noqa: E402

TS = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00$')
ID = re.compile(r'^(CASE-[0-9a-f]{32}|manual-[0-9a-f]{12}|live-[0-9a-f]{16}|[0-9a-f]{12}|[0-9a-f]{32})$')


class Normalizer:
    """時刻を <TS>、ランダムな ID を初出順の <ID:n> に置き換える。422 の detail は type・loc・msg だけ残す。"""

    def __init__(self):
        self.ids = {}

    def __call__(self, value):
        if isinstance(value, dict):
            return {k: self(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self(v) for v in value]
        if isinstance(value, str):
            if TS.match(value):
                return '<TS>'
            if ID.match(value):
                self.ids.setdefault(value, f'<ID:{len(self.ids)}>')
                return self.ids[value]
        return value

    def response(self, status, body):
        if status == 422 and isinstance(body, dict) and isinstance(body.get('detail'), list):
            body = {'detail': [{'type': e['type'], 'loc': e['loc'], 'msg': e['msg']} for e in body['detail']]}
        return self(body)


URL = 'https://example.org/workshop/brake'
GRADE = 'e:HEV（デモ仕様）'


def grounded(links=None, suggestions='<p>検索候補</p>', extra=None):
    chunks = [{'web': {'uri': u, 'title': t}} for u, t in (links or [(URL, '整備記事')])]
    candidate = {'finishReason': 'STOP', 'content': {'parts': [{'text': '根拠のある調査結果'}]},
                 'groundingMetadata': {'groundingChunks': chunks, 'searchEntryPoint': {'renderedContent': suggestions}}}
    candidate.update(extra or {})
    return {'status': 200, 'json': {'candidates': [candidate]}}


def price(**changes):
    record = dict(job_id='brake', source_url=URL, labor_price=6600, parts_price=12000, total_price=None, tax_included=True,
                  tax_rate=0.1, vehicle_match='exact', work_matches=True, work_conditions='前輪左右', published_at=None,
                  evidence='工賃6,600円（税込）')
    record.update(changes)
    return record


def extracted(data):
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return {'status': 200, 'json': {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': text}]}}]}}


def item(**changes):
    record = dict(job_id='brake', selected_source_ids=['brake-0', 'brake-1', 'brake-2'], labor_price=6000, parts_price=12000,
                  conditions='前輪左右', adjustment_reason='')
    record.update(changes)
    return record


def quote(**changes):
    body = dict(vehicle_id='FL4', year=2023, grade=GRADE, items=[item()], notes='テスト見積もり')
    body.update(changes)
    return body


def live(year, job_ids=('brake',), **changes):
    body = dict(vehicle_id='FL4', year=year, grade=GRADE, job_ids=list(job_ids), mode='live')
    body.update(changes)
    return body


def live_quote(ref, year, source_ids, **changes):
    body = dict(mode='live', research_id={'$ref': ref + '.research_id'}, vehicle_id='FL4', year=year, grade=GRADE,
                items=[item(selected_source_ids=source_ids, labor_price=6000)], notes='')
    body.update(changes)
    return body


def steps():
    s = []

    def add(name, method, path, body=None, **extra):
        s.append(dict(name=name, method=method, path=path, body=body, **extra))

    # 車両・作業・設定
    add('vehicles_all', 'GET', '/api/vehicles')
    add('vehicles_fl4', 'GET', '/api/vehicles?query=FL4')
    add('vehicles_civic', 'GET', '/api/vehicles?query=シビック')
    add('vehicles_case_fold', 'GET', '/api/vehicles?query=%20fl4%20')
    add('vehicles_live_origin', 'GET', '/api/vehicles?origin=live')
    add('vehicle_detail', 'GET', '/api/vehicles/FL4')
    add('vehicle_missing', 'GET', '/api/vehicles/nope')
    add('jobs', 'GET', '/api/repair-jobs')
    add('config_on', 'GET', '/api/config')
    # Simulator の参考価格
    add('research_sim', 'POST', '/api/price-research', dict(vehicle_id='FL4', year=2023, grade=GRADE, job_ids=['brake']))
    add('research_sim_multi', 'POST', '/api/price-research', dict(vehicle_id='FL4', year=2023, grade=GRADE, job_ids=['bumper', 'brake', 'oil']))
    add('research_bad_year', 'POST', '/api/price-research', dict(vehicle_id='FL4', year=2100, grade=GRADE, job_ids=['brake']))
    add('research_bad_grade', 'POST', '/api/price-research', dict(vehicle_id='FL4', year=2023, grade='未登録仕様', job_ids=['brake']))
    add('research_bad_mode', 'POST', '/api/price-research', dict(vehicle_id='FL4', year=2023, grade=GRADE, job_ids=['brake'], mode='invalid'))
    add('research_dup_jobs', 'POST', '/api/price-research', dict(vehicle_id='FL4', year=2023, grade=GRADE, job_ids=['brake', 'brake']))
    add('research_unknown_job', 'POST', '/api/price-research', dict(vehicle_id='FL4', year=2023, grade=GRADE, job_ids=['x']))
    add('research_no_jobs', 'POST', '/api/price-research', dict(vehicle_id='FL4', year=2023, grade=GRADE, job_ids=[]))
    add('research_year_string', 'POST', '/api/price-research', dict(vehicle_id='FL4', year=' 2023 ', grade=GRADE, job_ids=['oil']))
    add('research_missing_vehicle', 'POST', '/api/price-research', dict(vehicle_id='nope', year=2023, grade=GRADE, job_ids=['brake']))
    add('research_extra_field', 'POST', '/api/price-research', dict(vehicle_id='FL4', year=2023, grade=GRADE, job_ids=['brake'], region='当別'))
    # 見積もりの保存（Simulator）
    add('est_basic', 'POST', '/api/estimates', quote())
    add('est_get', 'GET', '/api/estimates/{est_basic.id}')
    add('est_search_2023', 'GET', '/api/estimates?query=2023')
    add('est_search_brake', 'GET', '/api/estimates?query=ブレーキ')
    add('est_search_lower', 'GET', '/api/estimates?query=fl4')
    add('est_search_percent', 'GET', '/api/estimates?query=%25')
    add('est_search_none', 'GET', '/api/estimates?query=存在しない')
    add('est_even_median', 'POST', '/api/estimates', quote(items=[item(selected_source_ids=['brake-0', 'brake-2', 'brake-3'], labor_price=6500)]))
    add('est_zero_no_reason', 'POST', '/api/estimates', quote(items=[item(selected_source_ids=[])]))
    add('est_zero_manual', 'POST', '/api/estimates', quote(items=[item(selected_source_ids=[], labor_price=7201, adjustment_reason='手入力')]))
    add('est_reason_spaces', 'POST', '/api/estimates', quote(items=[item(labor_price=7000, adjustment_reason='　 ')]))
    for i, patch_ in enumerate([dict(labor_price=-1), dict(parts_price=1.5), dict(labor_price=True), dict(parts_price=10000001),
                                dict(selected_source_ids=['oil-0']), dict(selected_source_ids=['brake-0', 'brake-0']),
                                dict(labor_price=9000), dict(labor_price=6000.0), dict(labor_price='6000')]):
        add(f'est_tamper_{i}', 'POST', '/api/estimates', quote(items=[item(**patch_)]))
    add('est_total_injected', 'POST', '/api/estimates', {**quote(), 'total_amount': 1})
    add('est_items_duplicated', 'POST', '/api/estimates', quote(items=[item(), item()]))
    add('est_too_many_items', 'POST', '/api/estimates', quote(items=[item(job_id=j, selected_source_ids=[]) for j in ['brake', 'oil', 'battery', 'filter', 'bumper', 'brake']]))
    add('est_research_in_sim', 'POST', '/api/estimates', quote(research_id='abc'))
    add('est_winter', 'POST', '/api/estimates', quote(winter_conditions=['salt_roads', 'cold_start', 'salt_roads']))
    add('est_winter_bad', 'POST', '/api/estimates', quote(winter_conditions=['snow']))
    add('est_missing', 'GET', '/api/estimates/nope')
    # 車両の手入力と複数作業
    add('manual_vehicle', 'POST', '/api/vehicles', dict(maker=' 手入力メーカー ', model='試験車', model_code='TEST', year=2020, grade='試験仕様'))
    add('manual_blank', 'POST', '/api/vehicles', dict(maker='  ', model='試験車', model_code='TEST', year=2020, grade='試験仕様'))
    add('manual_bad_year', 'POST', '/api/vehicles', dict(maker='m', model='試験車', model_code='TEST', year=1800, grade='試験仕様'))
    add('manual_missing_field', 'POST', '/api/vehicles', dict(maker='m', model='試験車', year=2020, grade='試験仕様'))
    add('manual_detail', 'GET', '/api/vehicles/{manual_vehicle.id}')
    add('est_multi', 'POST', '/api/estimates', quote(vehicle_id={'$ref': 'manual_vehicle.id'}, year=2020, grade='試験仕様', items=[
        item(), dict(job_id='oil', selected_source_ids=['oil-0'], labor_price=1000, parts_price=3501, conditions='フィルター別', adjustment_reason='')]))
    add('vehicles_after_manual', 'GET', '/api/vehicles')
    add('vehicles_search_manual', 'GET', '/api/vehicles?query=試験')
    # 案件
    add('case_create', 'POST', '/api/cases', dict(title=' 電話受付 ', recipient_name=' サンプル 太郎様 ', phone_memo=' 折り返しは明日。価格は診断後。 '))
    add('case_update_old_client', 'PUT', '/api/cases/{case_create.id}', dict(title='電話受付', status='estimating'))
    add('case_vehicle', 'POST', '/api/cases', dict(title='車両選択', vehicle_id='JB64W', vehicle_label='無視される'))
    add('case_vehicle_missing', 'POST', '/api/cases', dict(title='不存在', vehicle_id='unknown'))
    add('case_vehicle_keep', 'PUT', '/api/cases/{case_vehicle.id}', dict(title='旧クライアント', status='estimating'))
    for i, patch_ in enumerate([dict(title=' '), dict(status='other'), dict(amount=-1), dict(amount=1.5), dict(amount=True),
                                dict(amount=110000001), dict(due_date='2026-02-30'), dict(id='pretend'),
                                dict(latest_estimate_id='pretend'), dict(recipient_name='a' * 121), dict(phone_memo='a' * 6001),
                                dict(title=''), dict(vehicle_id=''), dict(due_date='2026-10-20T10:00:00')]):
        add(f'case_invalid_{i}', 'POST', '/api/cases', {'title': '試験', **patch_})
    add('case_missing_title', 'POST', '/api/cases', {})
    add('case_put_missing', 'PUT', '/api/cases/missing', dict(title='更新'))
    add('case_put_missing_blank', 'PUT', '/api/cases/missing', dict(title=' '))
    add('case_edit', 'PUT', '/api/cases/{case_create.id}', dict(title='更新案件', vehicle_label='FL4', status='estimating', amount=0,
                                                              due_date='2026-10-20', notes='部品待ち'))
    add('case_edit_null', 'PUT', '/api/cases/{case_create.id}', dict(title='更新案件', status='completed', amount=None, due_date=None,
                                                                   recipient_name='', phone_memo='', vehicle_id=None))
    add('case_date_forms', 'POST', '/api/cases', dict(title='日付', due_date='2026-10-20T00:00:00Z', amount=110000000))
    add('case_linked', 'POST', '/api/cases', dict(title='受付案件', amount=9000, due_date='2026-10-20', notes='受付メモ'))
    add('case_other', 'POST', '/api/cases', dict(title='別案件'))
    add('est_linked', 'POST', '/api/estimates', dict(case_id={'$ref': 'case_linked.id'}, vehicle_id='FL4', year=2023, grade=GRADE,
                                                       items=[dict(job_id='oil', selected_source_ids=['oil-0'], labor_price=1000, parts_price=5000,
                                                                   conditions='検証', adjustment_reason='')]))
    add('est_bad_link', 'POST', '/api/estimates', quote(case_id='missing'))
    add('est_legacy_no_case', 'POST', '/api/estimates', quote(case_id='', items=[item(job_id='bumper', selected_source_ids=['bumper-0'], labor_price=15000, parts_price=0)]))
    add('cases_list', 'GET', '/api/cases')
    add('estimates_list', 'GET', '/api/estimates')
    # Gemini（模擬応答）
    add('live_no_key', 'POST', '/api/price-research', live(2015), env='')
    add('config_off', 'GET', '/api/config', env='')
    add('live_research', 'POST', '/api/price-research', live(2023), gemini=[grounded(), extracted({'sources': [price()]})], reset_throttle=True)
    add('live_cached', 'POST', '/api/price-research', live(2023), gemini=[])
    add('est_live', 'POST', '/api/estimates', live_quote('live_research', 2023, [{'$ref': 'live_research.sources.brake.0.id'}]))
    add('est_live_get', 'GET', '/api/estimates/{est_live.id}')
    add('est_live_wrong_year', 'POST', '/api/estimates', live_quote('live_research', 2024, [{'$ref': 'live_research.sources.brake.0.id'}]))
    add('est_live_forged', 'POST', '/api/estimates', live_quote('live_research', 2023, [], research_id='forged'))
    add('est_live_no_research', 'POST', '/api/estimates', live_quote('live_research', 2023, [], research_id=None))
    add('est_live_winter', 'POST', '/api/estimates', live_quote('live_research', 2023, [{'$ref': 'live_research.sources.brake.0.id'}], winter_conditions=['salt_roads']))
    add('est_live_sim_ids', 'POST', '/api/estimates', live_quote('live_research', 2023, ['brake-0']))
    add('live_quota', 'POST', '/api/price-research', live(2016), gemini=[{'status': 429}], reset_throttle=True)
    add('live_throttled', 'POST', '/api/price-research', live(2017), gemini=[])
    add('live_malformed', 'POST', '/api/price-research', live(2017), gemini=[{'status': 200, 'json': {'candidates': []}}], reset_throttle=True)
    add('live_transient', 'POST', '/api/price-research', live(2018), gemini=[{'status': 503}, grounded(), extracted({'sources': [price()]})], reset_throttle=True)
    add('live_404', 'POST', '/api/price-research', live(2019), gemini=[{'status': 404}], reset_throttle=True)
    add('live_503_twice', 'POST', '/api/price-research', live(2019), gemini=[{'status': 503}, {'status': 503}], reset_throttle=True)
    add('live_400_key', 'POST', '/api/price-research', live(2019), gemini=[{'status': 400, 'json': {'error': {'message': 'API key not valid. SECRET'}}}], reset_throttle=True)
    add('live_400_other', 'POST', '/api/price-research', live(2019), gemini=[{'status': 400, 'json': {'error': {'message': 'bad schema'}}}], reset_throttle=True)
    add('live_403', 'POST', '/api/price-research', live(2019), gemini=[{'status': 403}], reset_throttle=True)
    add('live_418', 'POST', '/api/price-research', live(2019), gemini=[{'status': 418}], reset_throttle=True)
    add('live_unfinished', 'POST', '/api/price-research', live(2019), gemini=[{'status': 200, 'json': {'candidates': [{'finishReason': 'MAX_TOKENS', 'content': {'parts': [{'text': 'x'}]}}]}}], reset_throttle=True)
    add('live_thought_only', 'POST', '/api/price-research', live(2019), gemini=[{'status': 200, 'json': {'candidates': [{'content': {'parts': [{'text': 'x', 'thought': True}]}}]}}], reset_throttle=True)
    add('live_no_sources', 'POST', '/api/price-research', live(2020, ['filter']), gemini=[{'status': 200, 'json': {'candidates': [{'content': {'parts': [{'text': '見つかりません'}]}}]}}], reset_throttle=True)
    add('est_live_manual', 'POST', '/api/estimates', dict(mode='live', research_id={'$ref': 'live_no_sources.research_id'}, vehicle_id='FL4', year=2020, grade=GRADE,
                                                            items=[dict(job_id='filter', selected_source_ids=[], labor_price=7000, parts_price=0, conditions='', adjustment_reason='根拠不足のため手入力')]))
    other = 'https://garage.example.jp/price'
    mixed = [price(), price(), price(source_url='https://invented.example/a'), price(job_id='oil'),
             price(source_url=other, evidence='料金4,800〜6,300円'), price(source_url=other, evidence='工賃 ５，０００ － ６，０００円'),
             price(source_url=other, tax_included=None, evidence='工賃5,000円'), price(job_id='oil', source_url=other, labor_price=2200, tax_rate=0.1, evidence='オイル交換工賃2,200円'),
             price(job_id='oil', source_url=URL, labor_price=None, parts_price=None, total_price=None, evidence='金額なし'),
             price(job_id='oil', source_url=URL, labor_price=2100, tax_rate=0.05, evidence='2,100円（税込）'),
             price(job_id='brake', source_url='https://third.example.com/', labor_price=5400, tax_included=True, tax_rate=0.08, evidence='5,400円（税込）'),
             price(job_id='brake', source_url='https://fourth.example.com/', labor_price=5000, tax_included=False, tax_rate=None, vehicle_match='similar', evidence='5,000円'),
             price(job_id='brake', source_url='https://fifth.example.com/', labor_price=5000, tax_included=False, tax_rate=None, evidence='5,000円'),
             price(job_id='brake', source_url='https://sixth.example.com/', labor_price=5000, tax_included=False, tax_rate=None, evidence='   ')]
    links = [(URL, '整備記事'), (other, ''), ('https://third.example.com/', '三'), ('https://fourth.example.com/', '四'),
             ('https://fifth.example.com/', '五'), ('https://sixth.example.com/', '六'), ('http://insecure.example/', '安全でない'),
             ('https://localhost/', 'ローカル'), ('https://10.0.0.1/', '私設')]
    add('live_mixed', 'POST', '/api/price-research', live(2021, ['brake', 'oil']), gemini=[
        grounded(links, extra={'urlContextMetadata': {'urlMetadata': [
            {'retrievedUrl': 'https://context.example.net/a', 'urlRetrievalStatus': 'URL_RETRIEVAL_STATUS_SUCCESS'},
            {'retrievedUrl': URL, 'urlRetrievalStatus': 'URL_RETRIEVAL_STATUS_SUCCESS'},
            {'retrievedUrl': 'https://failed.example.net/', 'urlRetrievalStatus': 'URL_RETRIEVAL_STATUS_ERROR'}]}}),
        extracted({'sources': mixed})], reset_throttle=True)
    add('est_live_mixed', 'POST', '/api/estimates', dict(mode='live', research_id={'$ref': 'live_mixed.research_id'}, vehicle_id='FL4', year=2021, grade=GRADE, items=[
        dict(job_id='brake', selected_source_ids=[{'$ref': 'live_mixed.sources.brake.0.id'}, {'$ref': 'live_mixed.sources.brake.2.id'}], labor_price=5500, parts_price=0, conditions='', adjustment_reason=''),
        dict(job_id='oil', selected_source_ids=[{'$ref': 'live_mixed.sources.oil.0.id'}, {'$ref': 'live_mixed.sources.oil.1.id'}], labor_price=4000, parts_price=0, conditions='', adjustment_reason='')]))
    add('live_bad_money', 'POST', '/api/price-research', live(2022), gemini=[grounded(), extracted({'sources': [price(labor_price=-1)]})], reset_throttle=True)
    add('live_float_money', 'POST', '/api/price-research', live(2022), gemini=[grounded(), extracted('{"sources": [' + json.dumps(price(), ensure_ascii=False).replace('6600', '6600.0') + ']}')], reset_throttle=True)
    add('live_not_json', 'POST', '/api/price-research', live(2022), gemini=[grounded(), extracted('not json')], reset_throttle=True)
    add('live_empty_data', 'POST', '/api/price-research', live(2022), gemini=[grounded(), extracted({})], reset_throttle=True)
    add('live_extra_key', 'POST', '/api/price-research', live(2024), gemini=[grounded(), extracted({'sources': [price(note='x')]})], reset_throttle=True)
    return s


def resolve(value, results):
    if isinstance(value, dict):
        if set(value) == {'$ref'}:
            return lookup(value['$ref'], results)
        return {k: resolve(v, results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, results) for v in value]
    return value


def lookup(ref, results):
    name, *keys = ref.split('.')
    value = results[name]
    for key in keys:
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def mock_response(spec):
    if 'json' in spec:
        return httpx.Response(spec['status'], json=spec['json'])
    return httpx.Response(spec['status'], text=spec.get('text', ''))


def run_api():
    norm = Normalizer()
    out = []
    with tempfile.TemporaryDirectory() as temp:
        module.DB_PATH = Path(temp) / 'golden.sqlite3'
        with TestClient(module.app) as client:
            results = {}
            for step in steps():
                if step.get('reset_throttle'):
                    gemini._last_request = 0
                path = re.sub(r'\{([^}]+)\}', lambda m: lookup(m.group(1), results), step['path'])
                body = resolve(step['body'], results)
                env = {'GEMINI_API_KEY': step.get('env', 'test-placeholder')}
                with patch.dict(os.environ, env), patch('gemini.time.sleep'), patch('gemini.httpx.Client') as factory:
                    post = factory.return_value.__enter__.return_value.post
                    post.side_effect = [mock_response(r) for r in step.get('gemini', [])]
                    response = client.request(step['method'], path, json=body) if body is not None else client.request(step['method'], path)
                    calls = [dict(url=c.args[0], has_key=c.kwargs['headers'].get('x-goog-api-key') == 'test-placeholder', json=c.kwargs['json'])
                             for c in post.call_args_list]
                data = response.json()
                results[step['name']] = data
                record = dict(step)
                record.update(status=response.status_code, response=norm.response(response.status_code, data), calls=calls)
                out.append(record)
    return out


def run_pure():
    norm = Normalizer()
    urls = ['https://example.org/a', 'http://example.org', 'https://127.0.0.1/', 'https://localhost/', 'https://user:pass@example.org/',
            'https://user@example.org/', 'https://@example.org/', 'https://[::1]/', 'https://[::ffff:8.8.8.8]/', 'https://[::ffff:10.0.0.1]/',
            'https://8.8.8.8/', 'https://10.1.2.3/', 'https://172.16.0.1/', 'https://172.32.0.1/', 'https://192.168.1.1/', 'https://100.64.0.1/',
            'https://100.128.0.1/', 'https://169.254.1.1/', 'https://192.0.0.9/', 'https://192.0.2.1/', 'https://224.0.0.1/',
            'https://255.255.255.255/', 'https://0.1.2.3/', 'https://01.2.3.4/', 'https://1.2.3/', 'https://example.org:443/',
            'https://example.org:0443/', 'https://example.org:8443/', 'https://example.org:/', 'https://example.org:99999/',
            'https://example.org:abc/', 'https://EXAMPLE.ORG/', 'HTTPS://example.org/', ' https://example.org/ ', 'https://example/',
            'https://foo.local/', 'https://foo.internal/', 'https://foo.localhost/', 'https://[example.org/', 'https://example.org]/',
            'https://[v1.abc]/', 'https:example.org', '//example.org/', 'https://exa\tmple.org/', 'https://例え.jp/', 'https://ｅｘａｍｐｌｅ.org/',
            'https://a.b%2F/', '', 'https://', 'https://xn--r8jz45g.jp/path?q=1#f', 'https://[2001:db8::1]/', 'https://[64:ff9b::8.8.8.8]/']
    public = [dict(url=u, result=gemini.public_url(u)) for u in urls] + [dict(url=None, result=gemini.public_url(None))]

    def extract(data, job_ids, citations=None, warnings=None):
        result = {'data': data, 'citations': citations if citations is not None else [{'url': URL, 'title': '記事'}], 'warnings': list(warnings or [])}
        try:
            groups = gemini.extract_prices(result, job_ids)
            return dict(groups=norm(groups), warnings=result['warnings'])
        except HTTPException as error:
            return dict(status=error.status_code, detail=error.detail, warnings=result['warnings'])

    extract_cases = []
    for name, data, jobs in [
        ('valid', {'sources': [price()]}, ['brake']),
        ('tax_unknown', {'sources': [price(tax_included=None)]}, ['brake']),
        ('rate_unknown', {'sources': [price(tax_rate=None)]}, ['brake']),
        ('total_only', {'sources': [price(labor_price=None, total_price=19800)]}, ['brake']),
        ('similar', {'sources': [price(vehicle_match='similar')]}, ['brake']),
        ('work_unknown', {'sources': [price(work_matches=None)]}, ['brake']),
        ('tax_excluded', {'sources': [price(tax_included=False, tax_rate=None, labor_price=5999)]}, ['brake']),
        ('rate_005', {'sources': [price(labor_price=6299, tax_rate=0.05)]}, ['brake']),
        ('rate_008', {'sources': [price(labor_price=6479, tax_rate=0.08)]}, ['brake']),
        ('fabricated_dup_wrong_job', {'sources': [price(), price(), price(source_url='https://invented.example/a'), price(job_id='oil')]}, ['brake']),
        ('range', {'sources': [price(evidence='料金4,800〜6,300円')]}, ['brake']),
        ('assumed', {'sources': [price(evidence='4.0Lと仮定し算出した部品代6,320円')]}, ['brake']),
        ('guide', {'sources': [price(evidence='工賃の目安6,000円')]}, ['brake']),
        ('dash_range', {'sources': [price(evidence='¥4,800 - ¥6,300')]}, ['brake']),
        ('fullwidth_range', {'sources': [price(evidence='４８００－６３００円')]}, ['brake']),
        ('ideographic_space_range', {'sources': [price(evidence='4800　-　6300円')]}, ['brake']),
        ('condition_range', {'sources': [price(work_conditions='1〜2時間')]}, ['brake']),
        ('hyphen_in_text', {'sources': [price(evidence='工賃6,600円 - 税込')]}, ['brake']),
        ('blank_evidence', {'sources': [price(evidence=' 　')]}, ['brake']),
        ('five_sources', {'sources': [price(source_url=f'https://s{i}.example.com/') for i in range(5)]}, ['brake']),
        ('negative', {'sources': [price(labor_price=-1)]}, ['brake']),
        ('too_long_evidence', {'sources': [price(evidence='あ' * 121)]}, ['brake']),
        ('bad_rate', {'sources': [price(tax_rate=0.07)]}, ['brake']),
        ('bool_money', {'sources': [price(labor_price=True)]}, ['brake']),
        ('string_bool', {'sources': [price(tax_included='true')]}, ['brake']),
        ('missing_field', {'sources': [{k: v for k, v in price().items() if k != 'evidence'}]}, ['brake']),
        ('no_rate_key', {'sources': [{k: v for k, v in price().items() if k != 'tax_rate'}]}, ['brake']),
        ('none', None, ['brake', 'oil']),
        ('empty_dict', {}, ['brake']),
        ('empty_list', [], ['brake']),
        ('list', [1], ['brake']),
        ('extra_top', {'sources': [], 'x': 1}, ['brake']),
        ('too_many', {'sources': [price(source_url=f'https://s{i}.example.com/') for i in range(21)]}, ['brake']),
    ]:
        citations = [{'url': URL, 'title': '記事'}] + [{'url': f'https://s{i}.example.com/', 'title': f'S{i}'} for i in range(21)]
        extract_cases.append(dict(name=name, data=data, job_ids=jobs, citations=citations, output=extract(data, jobs, citations)))

    target = dict(vehicle_id='FL4', maker='ホンダ', model='シビック', model_code='FL4', year=2023, grade=GRADE,
                  jobs=[{k: j[k] for k in ('id', 'name', 'description')} for j in module.JOBS if j['id'] in ['brake', 'oil']])
    cache_key = hashlib.sha256(json.dumps({'kind': 'prices', 'target': target, 'model': gemini.MODEL}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    medians = [[6000], [5000, 6000], [5000, 6000, 8000], [5000, 8000, 6000, 6001], [1, 2], [0], [10000000, 9999999], [3, 1, 2, 4]]
    return dict(
        simulator={job['id']: module.sources_for(job) for job in module.JOBS},
        jobs=module.JOBS,
        public_url=public,
        extract=extract_cases,
        schema=gemini.Prices.model_json_schema(),
        generation_schema=gemini.generation_schema(gemini.Prices.model_json_schema()),
        cache=dict(target=target, key=cache_key, dumps=json.dumps(target, ensure_ascii=False)),
        median=[dict(values=v, result=int(median(v))) for v in medians],
    )


def main():
    (HERE / 'api.json').write_text(json.dumps(run_api(), ensure_ascii=False, indent=1) + '\n')
    (HERE / 'pure.json').write_text(json.dumps(run_pure(), ensure_ascii=False, indent=1) + '\n')
    print('wrote api.json and pure.json')


if __name__ == '__main__':
    main()
