"""M26: simulate how paired purchase/sales price changes affect gross margin."""

from uuid import uuid4

from .core import DEMO_DATE, ValidationError, approved_by, decimal_value, demo_item, text_value


SPEC = {
    'idea_id': 'M26',
    'title': '材料粗利影響試算',
    'description': '同一条件の旧・新仕入/販売価格版から、数量に応じた粗利差を試算します。',
    'defaults': {
        'action': 'seed_demo',
        'item_id': 'demo-paint',
        'unit': 'ml',
        'quantity': '10',
        'transaction_conditions': {},
        'confirmed_by': '架空デモ担当',
    },
}

NAMESPACE = 'gross_margin_simulation'
_ROLE_TYPES = {
    'old_purchase': '仕入', 'old_sales': '販売',
    'new_purchase': '仕入', 'new_sales': '販売',
}


def run(payload: dict, store) -> dict:
    """Simulate margin only; never save or alter an item price."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'simulate')
    if action == 'seed_demo':
        _check_keys(payload, {'action', 'item_id', 'unit', 'quantity', 'transaction_conditions', 'confirmed_by'})
        ids = _seed_demo(payload, store)
        return _simulate(payload | ids, store, simulator=True)
    if action == 'simulate':
        _check_keys(payload, {'action', 'item_id', 'unit', 'quantity', 'transaction_conditions',
                              *_ROLE_TYPES.keys(), 'confirmed_by'})
        return _simulate(payload, store, simulator=False)
    if action == 'list':
        _check_keys(payload, {'action'})
        rows = store.records(NAMESPACE)
        return {'simulations': rows, 'simulation_only': True,
                'notice': _notice(), 'simulator': any(row.get('simulator') for row in rows)}
    raise ValidationError('action: simulate / seed_demo / list を選択してください')


def _check_keys(payload, allowed):
    if set(payload) - allowed:
        raise ValidationError('payload: 指定できない項目があります')


def _criteria(payload):
    item_id = text_value(payload.get('item_id'), 'item_id')
    unit = text_value(payload.get('unit'), 'unit')
    quantity = decimal_value(payload.get('quantity'), 'quantity', positive=True)
    conditions = payload.get('transaction_conditions', {})
    if not isinstance(conditions, dict):
        raise ValidationError('transaction_conditions: 条件の集合を指定してください')
    return item_id, unit, quantity, conditions


def _seed_demo(payload, store):
    item_id, unit, _, conditions = _criteria(payload)
    confirmer = approved_by(payload)
    if (item_id, unit, conditions) != ('demo-paint', 'ml', {}):
        raise ValidationError('seed_demo: 架空デモ条件を指定してください')
    versions = store.price_versions(item_id)
    matching = [v for v in versions if v.get('metadata', {}).get('transaction_conditions', {}) == conditions
                and v.get('supplier_id', '') == '']
    ids = {}
    # Reuse only the shared core's known fictional seed as the new-price pair.
    if matching:
        demo_pair = {}
        for price_type, amount in (('仕入', '80'), ('販売', '120')):
            candidates = [v for v in matching if v.get('item', {}).get('price_type') == price_type
                          and v.get('item', {}).get('unit') == unit
                          and v.get('item', {}).get('unit_price') == amount
                          and v.get('item', {}).get('source') == 'simulator:架空値']
            if len(candidates) != 1:
                raise ValidationError('seed_demo: 既存価格版があるため、指定の架空seedを確認できません')
            demo_pair[price_type] = candidates[0]['price_version_id']
        ids['new_purchase'] = demo_pair['仕入']
        ids['new_sales'] = demo_pair['販売']
    else:
        ids['new_purchase'] = ids['new_sales'] = None
    for role, price_type, amount, effective in (
        ('old_purchase', '仕入', '70', '2026-08-01'),
        ('old_sales', '販売', '105', '2026-08-01'),
        ('new_purchase', '仕入', '80', DEMO_DATE),
        ('new_sales', '販売', '120', DEMO_DATE),
    ):
        if role.startswith('new_') and ids[role] is not None:
            continue
        item = demo_item(item_id=item_id, price_type=price_type, unit_price=amount, unit=unit)
        item['updated_at'] = effective
        item['source'] = 'simulator:架空M26価格'
        version = store.add_price(item, confirmer, valid_from=effective,
                                  transaction_conditions=conditions)
        ids[role] = version['price_version_id']
    return ids


def _simulate(payload, store, *, simulator):
    item_id, unit, quantity, conditions = _criteria(payload)
    version_ids = {role: text_value(payload.get(role), role) for role in _ROLE_TYPES}
    all_versions = store.price_versions(item_id)
    by_id = {v['price_version_id']: v for v in all_versions}
    selected = {}
    for role, price_type in _ROLE_TYPES.items():
        version = by_id.get(version_ids[role])
        if version is None:
            raise ValidationError(f'{role}: 指定価格版が品目にありません')
        item = version.get('item', {})
        metadata = version.get('metadata', {})
        if version.get('status') != 'approved':
            raise ValidationError(f'{role}: 承認済み価格版が必要です')
        if item.get('item_id') != item_id or item.get('unit') != unit:
            raise ValidationError(f'{role}: 品目IDまたは単位が一致しません')
        if item.get('price_type') != price_type:
            raise ValidationError(f'{role}: 価格区分が一致しません')
        if metadata.get('transaction_conditions', {}) != conditions:
            raise ValidationError(f'{role}: 取引条件が一致しません')
        if metadata.get('currency', 'JPY') != 'JPY':
            raise ValidationError(f'{role}: 通貨条件が一致しません')
        selected[role] = version
    suppliers = {version.get('supplier_id', '') for version in selected.values()}
    if len(suppliers) != 1:
        raise ValidationError('supplier_id: 仕入先条件が一致しません')
    prices = {role: decimal_value(version['item']['unit_price'], role) for role, version in selected.items()}
    old_unit_margin = prices['old_sales'] - prices['old_purchase']
    new_unit_margin = prices['new_sales'] - prices['new_purchase']
    old_margin = old_unit_margin * quantity
    new_margin = new_unit_margin * quantity
    saved = store.put(NAMESPACE, {
        'item_id': item_id, 'unit': unit, 'quantity': str(quantity),
        'transaction_conditions': conditions,
        'price_version_ids': version_ids,
        'prices': {role: str(price) for role, price in prices.items()},
        'old_unit_gross_margin': str(old_unit_margin),
        'new_unit_gross_margin': str(new_unit_margin),
        'old_gross_margin': str(old_margin), 'new_gross_margin': str(new_margin),
        'gross_margin_change': str(new_margin - old_margin),
        'confirmed_by': approved_by(payload),
        'simulation_only': True, 'simulator': simulator,
        'excluded_costs': ['人件費', '税', '廃棄'],
    }, record_id=uuid4().hex)
    return {'status': 'simulated', 'simulation': saved, 'simulation_only': True,
            'simulator': simulator or any(v['item'].get('source', '').startswith('simulator:')
                                           for v in selected.values()),
            'notice': _notice()}


def _notice():
    return '粗利影響の試算のみです。価格は変更しません。人件費・税・廃棄を含みません。'
