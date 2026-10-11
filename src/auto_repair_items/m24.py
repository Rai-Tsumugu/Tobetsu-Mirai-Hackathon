"""M24: show an item's approved price versions as a condition-matched timeline."""

import json

from .core import DEMO_DATE, ValidationError, approved_by, demo_item, dumps, text_value


SPEC = {
    'idea_id': 'M24',
    'title': '価格履歴タイムライン',
    'description': '同一品目・単位・価格区分・仕入先・取引条件の価格版を時系列で確認します。',
    'defaults': {
        'action': 'timeline',
        'item_id': 'demo-paint',
        'unit': 'ml',
        'price_type': '販売',
        'supplier_id': '',
        'transaction_conditions': {},
    },
}


def run(payload: dict, store) -> dict:
    """Return matching versions, or explicitly add a fictional demo history."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'timeline')
    if action == 'seed_demo':
        _check_keys(payload, {'action', 'item_id', 'unit', 'price_type', 'supplier_id',
                              'transaction_conditions', 'confirmed_by'})
        _seed_demo(payload, store)
        return _timeline(payload, store)
    if action == 'timeline':
        _check_keys(payload, {'action', 'item_id', 'unit', 'price_type', 'supplier_id',
                              'transaction_conditions'})
        return _timeline(payload, store)
    raise ValidationError('action: timeline / seed_demo を選択してください')


def _check_keys(payload, allowed):
    if set(payload) - allowed:
        raise ValidationError('payload: 指定できない項目があります')


def _criteria(payload):
    item_id = text_value(payload.get('item_id'), 'item_id')
    unit = text_value(payload.get('unit'), 'unit')
    price_type = text_value(payload.get('price_type'), 'price_type')
    if price_type not in ('仕入', '販売'):
        raise ValidationError('price_type: 仕入 / 販売を選択してください')
    supplier_id = payload.get('supplier_id', '')
    if not isinstance(supplier_id, str):
        raise ValidationError('supplier_id: 文字列を指定してください')
    conditions = payload.get('transaction_conditions', {})
    if not isinstance(conditions, dict):
        raise ValidationError('transaction_conditions: 条件の集合を指定してください')
    return item_id, unit, price_type, supplier_id, conditions


def _seed_demo(payload, store):
    item_id, unit, price_type, supplier_id, conditions = _criteria(payload)
    confirmer = approved_by(payload)
    if (item_id, unit, price_type, supplier_id, conditions) != ('demo-paint', 'ml', '販売', '', {}):
        raise ValidationError('seed_demo: 架空デモ条件を指定してください')
    if store.price_versions(item_id, price_type, supplier_id):
        return
    for effective_date, amount, checked_at in (
        ('2026-08-01', '110', '2026-08-02'),
        (DEMO_DATE, '120', DEMO_DATE),
    ):
        item = demo_item(item_id=item_id, price_type=price_type, unit=unit,
                         unit_price=amount)
        item['updated_at'] = effective_date
        item['source'] = 'simulator:架空価格履歴'
        store.add_price(
            item, confirmer, supplier_id=supplier_id, valid_from=effective_date,
            checked_at=checked_at,
            transaction_conditions=conditions,
        )


def _timeline(payload, store):
    item_id, unit, price_type, supplier_id, conditions = _criteria(payload)
    all_versions = store.price_versions(item_id)
    matching = []
    other_groups = {}
    for index, version in enumerate(all_versions):
        item = version.get('item', {})
        metadata = version.get('metadata', {})
        version_conditions = metadata.get('transaction_conditions', {})
        group_key = (item.get('unit'), item.get('price_type'), version.get('supplier_id', ''),
                     dumps(version_conditions))
        expected_key = (unit, price_type, supplier_id, conditions)
        if group_key[:3] == expected_key[:3] and group_key[3] == dumps(expected_key[3]):
            if version.get('status') == 'approved':
                matching.append((index, version))
        else:
            other_groups.setdefault(group_key, []).append(version)

    matching.sort(key=lambda pair: (pair[1]['valid_from'], pair[0]))
    versions = [_version_row(version) for _, version in matching]
    result = {
        'item_id': item_id, 'unit': unit, 'price_type': price_type,
        'supplier_id': supplier_id, 'transaction_conditions': conditions,
        'versions': versions,
        'comparison': '同一条件の履歴表示。相場を代表する値ではありません。',
        'simulator': any(row['source'].startswith('simulator:') for row in versions),
    }
    if not versions:
        result['unknowns'] = ['指定条件に一致する承認済み価格履歴がありません']
    if other_groups:
        result['incomparable_groups'] = [
            {
                'unit': key[0], 'price_type': key[1], 'supplier_id': key[2],
                'transaction_conditions': json.loads(key[3]),
                'reason': '単位・価格区分・仕入先・取引条件の不一致により比較対象外',
                'versions': [_version_row(version) for version in rows
                             if version.get('status') == 'approved'],
            }
            for key, rows in other_groups.items()
        ]
    return result


def _version_row(version):
    item = version['item']
    metadata = version.get('metadata', {})
    return {
        'price_version_id': version['price_version_id'],
        'item_id': item['item_id'], 'unit': item['unit'],
        'price_type': item['price_type'], 'amount': item['unit_price'],
        'supplier_id': version.get('supplier_id', ''),
        'transaction_conditions': metadata.get('transaction_conditions', {}),
        'source': item['source'], 'confirmed_by': version['confirmed_by'],
        'checked_at': metadata.get('checked_at', item['updated_at']),
        'valid_from': version['valid_from'], 'valid_until': version.get('valid_until'),
        'status': version['status'],
    }
