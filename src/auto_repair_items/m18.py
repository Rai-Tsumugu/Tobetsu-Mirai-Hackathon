"""M18: keep conditional prices separate and require all terms to match."""

from .core import DEMO_DATE, ValidationError, approved_by, date_value, decimal_value, demo_item, text_value


SPEC = {
    'idea_id': 'M18',
    'title': '期限条件付き価格',
    'description': '数量・期間・単位が一致した場合だけ条件付き価格を見積候補として返します。',
    'defaults': {
        'action': 'apply', 'item_id': 'demo-m18-paint', 'quantity': '5',
        'unit': '缶', 'price_type': '仕入', 'as_of': DEMO_DATE,
    },
}

NAMESPACE = 'conditional_price'


def run(payload: dict, store) -> dict:
    """Record terms, list their status, or validate and return a quote candidate.

    Candidates are never inserted into Store's ordinary price table or returned
    as the shared unconditional ``items`` contract.
    """
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'apply')
    if action == 'record':
        _check_keys(payload, {'action', 'item_id', 'unit_price', 'min_qty', 'unit',
                              'valid_from', 'valid_until', 'price_type', 'source', 'confirmed_by'})
        return _record(payload, store)
    if action in ('list', 'apply'):
        _check_keys(payload, {'action', 'item_id', 'quantity', 'unit', 'price_type', 'as_of'})
        return _evaluate(payload, store, apply=action == 'apply')
    raise ValidationError('action: record / list / apply を選択してください')


def _check_keys(payload, allowed):
    if set(payload) - allowed:
        raise ValidationError('payload: 指定できない項目があります')


def _record(payload, store):
    item_id = text_value(payload.get('item_id'), 'item_id')
    unit = text_value(payload.get('unit'), 'unit')
    price_type = payload.get('price_type')
    if price_type != '仕入':
        raise ValidationError('price_type: 条件付き特価は仕入価格のみ登録できます')
    unit_price = decimal_value(payload.get('unit_price'), 'unit_price', positive=True)
    min_qty = decimal_value(payload.get('min_qty'), 'min_qty', positive=True)
    valid_from = date_value(payload.get('valid_from'), 'valid_from').isoformat()
    valid_until = date_value(payload.get('valid_until'), 'valid_until').isoformat()
    if valid_until < valid_from:
        raise ValidationError('valid_until: 開始日より前です')
    source = text_value(payload.get('source'), 'source')
    confirmer = approved_by(payload)
    # This private namespace intentionally bypasses Store.add_price().
    record = {
        'item_id': item_id, 'unit_price': str(unit_price), 'min_qty': str(min_qty),
        'unit': unit, 'valid_from': valid_from, 'valid_until': valid_until,
        'price_type': price_type, 'source': source, 'confirmed_by': confirmer,
    }
    saved = store.put(NAMESPACE, record)
    return {'status': 'saved', 'conditional_price_id': saved['record_id'],
            'conditional_price': record, 'simulator': False}


def _evaluate(payload, store, *, apply):
    item_id = text_value(payload.get('item_id'), 'item_id')
    quantity = decimal_value(payload.get('quantity'), 'quantity', positive=True)
    unit = text_value(payload.get('unit'), 'unit')
    price_type = payload.get('price_type', '仕入')
    if price_type != '仕入':
        raise ValidationError('price_type: 条件付き特価は仕入価格のみ対象です')
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    rows = store.records(NAMESPACE)
    if not rows and item_id == SPEC['defaults']['item_id']:
        _record({
            'item_id': item_id, 'unit_price': '6800', 'min_qty': '5', 'unit': '缶',
            'valid_from': '2026-10-01', 'valid_until': '2026-10-31',
            'price_type': '仕入', 'source': 'simulator:架空仕入条件', 'confirmed_by': '架空デモ担当',
        }, store)
        rows = store.records(NAMESPACE)
    matching = [row for row in rows if row['item_id'] == item_id]
    if not matching:
        raise ValidationError('条件付き価格未確認: 対象価格がありません')
    results = []
    eligible = []
    for row in matching:
        terms = row['valid_from'] <= as_of <= row['valid_until'] and quantity >= decimal_value(row['min_qty']) and unit == row['unit'] and price_type == row['price_type']
        status = '条件一致' if terms else '条件不一致'
        result = {
            'conditional_price_id': row['record_id'], 'item_id': item_id,
            'unit_price': row['unit_price'], 'min_qty': row['min_qty'], 'unit': row['unit'],
            'valid_from': row['valid_from'], 'valid_until': row['valid_until'],
            'price_type': row['price_type'], 'source': row['source'],
            'confirmed_by': row['confirmed_by'], 'as_of': as_of,
            'requested_quantity': str(quantity), 'requested_unit': unit, 'status': status,
        }
        results.append(result)
        if terms:
            eligible.append(result)
    if apply and not eligible:
        raise ValidationError('条件不一致: 数量・期間・単位を確認してください。通常価格を確認してください')
    response = {'item_id': item_id, 'price_type': price_type, 'as_of': as_of,
                'conditional_prices': results, 'simulator': any(row['source'].startswith('simulator:') for row in matching)}
    if apply:
        # A narrow quote-candidate envelope makes this conditional result
        # impossible to mistake for an unconditional Store item price.
        response['quote_candidate'] = dict(eligible[-1])
    return response
