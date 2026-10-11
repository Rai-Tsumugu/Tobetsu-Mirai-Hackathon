"""M15: track effective periods and human-confirmed price expiry."""

from .core import DEMO_DATE, PRICE_TYPES, ValidationError, approved_by, date_value, text_value


SPEC = {
    'idea_id': 'M15',
    'title': '品目別有効期限',
    'description': '価格版ごとの有効期間を追記し、期限なし・未確認・期限切れを区別します。',
    'defaults': {
        'action': 'list',
        'item_id': 'demo-m15-paint',
        'price_type': '仕入',
        'as_of': DEMO_DATE,
    },
}


def run(payload: dict, store) -> dict:
    """List price-version validity or append a human-confirmed period revision."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'list')
    if action == 'list':
        _check_keys(payload, {'action', 'item_id', 'price_type', 'as_of'})
        return _list_validity(payload, store)
    if action == 'set_validity':
        _check_keys(payload, {'action', 'item_id', 'price_type', 'supplier_id',
                              'valid_from', 'valid_until', 'reason', 'confirmed_by'})
        return _set_validity(payload, store)
    raise ValidationError('action: list / set_validity を選択してください')


def _check_keys(payload, allowed):
    if set(payload) - allowed:
        raise ValidationError('payload: 指定できない項目があります')


def _target(payload, *, required_date=False):
    item_id = text_value(payload.get('item_id'), 'item_id')
    price_type = payload.get('price_type', '仕入')
    if price_type not in PRICE_TYPES:
        raise ValidationError('price_type: 仕入または販売を選択してください')
    supplier_id = payload.get('supplier_id')
    if supplier_id is not None and supplier_id != '':
        supplier_id = text_value(supplier_id, 'supplier_id')
    return item_id, price_type, supplier_id


def _list_validity(payload, store):
    item_id, price_type, supplier_id = _target(payload)
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    versions = store.price_versions(item_id, price_type, supplier_id)
    if not versions and item_id == SPEC['defaults']['item_id'] and supplier_id is None:
        from .core import demo_item
        store.add_price(demo_item(item_id, price_type, '80'), '架空デモ担当',
                        valid_from=DEMO_DATE, reason='架空デモ初回登録', simulator=True)
        versions = store.price_versions(item_id, price_type)
    if not versions:
        raise ValidationError('価格未確認: 対象価格がありません')

    rows = []
    for version in versions:
        if version['status'] != 'approved':
            status = '未確認'
        elif version['valid_from'] > as_of:
            status = '未開始'
        elif version['valid_until'] is not None and as_of > version['valid_until']:
            status = '期限切れ'
        elif version['valid_until'] is None:
            status = '期限なし'
        else:
            status = '有効'
        rows.append({
            'price_version_id': version['price_version_id'],
            'item_id': item_id,
            'price_type': price_type,
            'supplier_id': version['supplier_id'],
            'unit_price': version['item']['unit_price'],
            'valid_from': version['valid_from'],
            'valid_until': version['valid_until'],
            'status': status,
            'confirmed_by': version['confirmed_by'],
            'reason': version['reason'],
        })
    return {'item_id': item_id, 'price_type': price_type, 'as_of': as_of,
            'price_versions': rows, 'simulator': any(
                bool((version.get('metadata') or {}).get('simulator')) for version in versions)}


def _set_validity(payload, store):
    item_id, price_type, supplier_id = _target(payload)
    confirmer = approved_by(payload)
    reason = text_value(payload.get('reason'), 'reason')
    versions = store.price_versions(item_id, price_type, supplier_id)
    approved = [(index, version) for index, version in enumerate(versions)
                if version['status'] == 'approved']
    if not approved:
        raise ValidationError('価格未確認: 承認済みの価格版がありません')
    current = max(approved, key=lambda pair: (pair[1]['valid_from'], pair[0]))[1]
    valid_from = date_value(payload.get('valid_from', current['valid_from']), 'valid_from').isoformat()
    raw_until = payload.get('valid_until')
    valid_until = date_value(raw_until, 'valid_until').isoformat() if raw_until is not None else None
    if valid_until is not None and valid_until < valid_from:
        raise ValidationError('valid_until: 開始日より前です')
    item = dict(current['item'])
    metadata = dict(current.get('metadata') or {})
    # Add a version with the same price and item facts; the old row remains intact.
    with store.transaction():
        version = store.add_price(
            item, confirmer, supplier_id=current['supplier_id'],
            valid_from=valid_from, valid_until=valid_until,
            status='approved', reason=reason, **metadata,
        )
    status = '期限なし' if valid_until is None else '有効'
    return {
        'status': 'saved', 'item_id': item_id, 'price_type': price_type,
        'price_version_id': version['price_version_id'],
        'previous_price_version_id': current['price_version_id'],
        'valid_from': version['valid_from'], 'valid_until': version['valid_until'],
        'price_status': status, 'confirmed_by': version['confirmed_by'],
        'reason': version['reason'], 'item': version['item'],
        'simulator': bool(metadata.get('simulator', False)),
    }
