"""M25: display manually recorded raw-material index observations as context."""

from datetime import datetime

from .core import ValidationError, decimal_value, text_value


SPEC = {
    'idea_id': 'M25',
    'title': '原料指数参考カード',
    'description': '手入力した原料指数を出所と利用条件の状態付きで参考表示します。',
    'defaults': {
        'action': 'seed_demo',
        'source': 'simulator:架空データ出典',
        'series': '架空ナフサ指数',
        'value': '123.4',
        'unit': '指数ポイント',
        'published_at': '2026-10-01',
        'fetched_at': '2026-10-11T09:00:00+09:00',
        'terms_status': '未確認',
    },
}

NAMESPACE = 'index_observation'
_FIELDS = ('source', 'series', 'value', 'unit', 'published_at', 'fetched_at', 'terms_status')


def run(payload: dict, store) -> dict:
    """Record or list observations; never derive or update an item price."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'list')
    if action == 'record':
        _check_keys(payload, {'action', *_FIELDS})
        return _record(payload, store, fictional=False)
    if action == 'seed_demo':
        _check_keys(payload, {'action', *_FIELDS})
        _record(payload, store, fictional=True)
        return _list(store)
    if action == 'list':
        _check_keys(payload, {'action'})
        return _list(store)
    raise ValidationError('action: record / list / seed_demo を選択してください')


def _check_keys(payload, allowed):
    if set(payload) - allowed:
        raise ValidationError('payload: 指定できない項目があります')


def _record(payload, store, *, fictional):
    source = text_value(payload.get('source'), 'source')
    series = text_value(payload.get('series'), 'series')
    value = decimal_value(payload.get('value'), 'value')
    unit = text_value(payload.get('unit'), 'unit')
    published_at = _timestamp(payload.get('published_at'), 'published_at')
    fetched_at = _timestamp(payload.get('fetched_at'), 'fetched_at')
    terms_status = text_value(payload.get('terms_status'), 'terms_status')
    record = {
        'source': source, 'series': series, 'value': str(value), 'unit': unit,
        'published_at': published_at, 'fetched_at': fetched_at,
        'terms_status': terms_status,
        'simulator': fictional,
        'notice': '参考情報のみ。利用規約・再利用条件は未確認。品目の個別価格へ自動反映しません。',
    }
    if fictional:
        if record['value'] != SPEC['defaults']['value'] or record['source'] != SPEC['defaults']['source']:
            raise ValidationError('seed_demo: 架空デモ値を指定してください')
    saved = store.put(NAMESPACE, record)
    return {'status': 'saved', 'observation_id': saved['record_id'],
            'observation': record, 'simulator': fictional}


def _list(store):
    observations = store.records(NAMESPACE)
    return {
        'observations': [{key: row[key] for key in (*_FIELDS, 'simulator', 'notice')}
                         for row in observations],
        'simulator': any(row.get('simulator', False) for row in observations),
        'notice': '参考情報のみ。指数を個別品目価格・見積価格へ自動反映しません。',
    }


def _timestamp(value, field):
    value = text_value(value, field)
    try:
        # Published dates may be date-only; fetch times must carry an explicit timezone.
        if field == 'published_at' and len(value) == 10:
            parsed = datetime.strptime(value, '%Y-%m-%d')
            return parsed.date().isoformat()
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValidationError(f'{field}: ISO形式の日付または日時が必要です') from None
    if field == 'fetched_at' and parsed.utcoffset() is None:
        raise ValidationError('fetched_at: タイムゾーン付き日時が必要です')
    return value
