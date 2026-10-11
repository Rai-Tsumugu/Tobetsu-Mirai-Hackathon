"""M16: prioritize prices that need a human freshness review."""

from .core import DEMO_DATE, PRICE_TYPES, ValidationError, approved_by, date_value, text_value


SPEC = {
    'idea_id': 'M16',
    'title': '更新待ち隊列',
    'description': '期限切れ・未確認・価格差分を明示した優先順位で並べ、人の確認状態を記録します。',
    'defaults': {
        'action': 'list',
        'as_of': DEMO_DATE,
    },
}

_PRIORITY = {'期限切れ': 0, '未確認': 1, '差分あり': 2}
_STATES = ('確認済み', '要調査')


def run(payload: dict, store) -> dict:
    """List review work or append a human review decision, without changing price."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'list')
    if action == 'list':
        _check_keys(payload, {'action', 'as_of'})
        return _list_queue(payload, store)
    if action == 'update_status':
        _check_keys(payload, {'action', 'item_id', 'price_type', 'supplier_id',
                              'status', 'confirmed_by', 'reason', 'checked_at', 'as_of'})
        return _update_status(payload, store)
    raise ValidationError('action: list / update_status を選択してください')


def _check_keys(payload, allowed):
    if set(payload) - allowed:
        raise ValidationError('payload: 指定できない項目があります')


def _list_queue(payload, store):
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()

    latest_states = {}
    for record in store.records('freshness_queue'):
        key = (record['item_id'], record['price_type'], record.get('supplier_id', ''))
        latest_states[key] = record

    latest_versions = {}
    histories = {}
    for version in store.price_versions():
        item = version['item']
        key = (item['item_id'], item['price_type'], version['supplier_id'])
        histories.setdefault(key, []).append(version)
        prior = latest_versions.get(key)
        index = len(histories[key]) - 1
        if prior is None or (version['valid_from'], index) >= (prior['valid_from'], prior['_index']):
            latest_versions[key] = {**version, '_index': index}

    rows = []
    for key, version in latest_versions.items():
        item_id, price_type, supplier_id = key
        checked = latest_states.get(key)
        if checked and checked.get('price_version_id') != version['price_version_id']:
            checked = None
        if (checked and checked['status'] == '確認済み'
                and checked.get('price_version_id') == version['price_version_id']):
            continue
        metadata = version.get('metadata') or {}
        checked_at = metadata.get('checked_at')
        valid_until = version.get('valid_until')
        if valid_until is not None and valid_until < as_of:
            reason = '期限切れ'
        elif version['status'] != 'approved' or not checked_at:
            reason = '未確認'
        else:
            versions = histories[key]
            position = version['_index']
            if position > 0 and versions[position - 1]['item']['unit_price'] != version['item']['unit_price']:
                reason = '差分あり'
            elif metadata.get('has_diff'):
                reason = '差分あり'
            else:
                continue
        rows.append({
            'item_id': item_id, 'name': version['item']['name'],
            'price_type': price_type, 'supplier_id': supplier_id,
            'price_version_id': version['price_version_id'],
            'unit_price': version['item']['unit_price'], 'unit': version['item']['unit'],
            'source': version['item']['source'], 'updated_at': version['item']['updated_at'],
            'valid_until': valid_until, 'reason': reason,
            'priority': _PRIORITY[reason],
            'status': checked['status'] if checked else '未対応',
            'confirmed_by': checked.get('confirmed_by') if checked else None,
            'review_reason': checked.get('reason') if checked else None,
            'checked_at': checked_at,
            'simulator': bool(metadata.get('simulator', False)
                               or version['item']['source'].startswith('simulator:')),
        })

    rows.sort(key=lambda row: (row['priority'], row['valid_until'] or '9999-12-31',
                               row['item_id'], row['price_type'], row['supplier_id']))
    return {'as_of': as_of, 'queue': rows, 'priority_order': list(_PRIORITY),
            'simulator': any(row['simulator'] for row in rows)}


def _update_status(payload, store):
    item_id = text_value(payload.get('item_id'), 'item_id')
    price_type = payload.get('price_type', '仕入')
    if price_type not in PRICE_TYPES:
        raise ValidationError('price_type: 仕入または販売を選択してください')
    supplier_id = payload.get('supplier_id', '')
    if supplier_id:
        supplier_id = text_value(supplier_id, 'supplier_id')
    status = payload.get('status')
    if status not in _STATES:
        raise ValidationError('status: 確認済みまたは要調査を選択してください')
    confirmer = approved_by(payload)
    reason = text_value(payload.get('reason'), 'reason')
    checked_at = date_value(payload.get('checked_at', payload.get('as_of', DEMO_DATE)), 'checked_at').isoformat()
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    if checked_at > as_of:
        raise ValidationError('checked_at: 基準日より未来の日付です')

    versions = store.price_versions(item_id, price_type, supplier_id)
    if not versions:
        raise ValidationError('価格未確認: 対象価格がありません')
    current = versions[-1]
    if status == '確認済み':
        item = dict(current['item'])
        metadata = dict(current.get('metadata') or {})
        metadata['checked_at'] = checked_at
        with store.transaction():
            revised = store.add_price(item, confirmer, supplier_id=supplier_id,
                valid_from=current['valid_from'], valid_until=current['valid_until'],
                status=current['status'], reason=reason, **metadata)
    else:
        revised = current

    saved = store.put('freshness_queue', {
        'item_id': item_id, 'price_type': price_type, 'supplier_id': supplier_id,
        'status': status, 'confirmed_by': confirmer, 'reason': reason,
        'checked_at': checked_at if status == '確認済み' else None,
        'price_version_id': revised['price_version_id'],
    }, record_id=f'{item_id}:{price_type}:{supplier_id}')
    return {'status': status, 'item_id': item_id, 'price_type': price_type,
            'supplier_id': supplier_id, 'confirmed_by': confirmer, 'reason': reason,
            'checked_at': checked_at if status == '確認済み' else None,
            'price_version_id': revised['price_version_id'],
            'unit_price': revised['item']['unit_price'], 'record_id': saved['record_id'],
            'simulator': bool((revised.get('metadata') or {}).get('simulator', False))}
