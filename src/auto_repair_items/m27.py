"""M27: show price deltas against a previous quote snapshot."""

from .core import DEMO_DATE, ValidationError, approved_by, date_value, decimal_value, demo_item, text_value


SPEC = {
    'idea_id': 'M27',
    'title': '見積バスケット差分通知',
    'description': '見積バスケットの現行価格と前回見積の同一条件価格を比較します。',
    'defaults': {
        'action': 'compare_demo',
        'quote_id': 'demo-m27-quote',
        'basket': [{'item_id': 'demo-m27-paint', 'unit': 'ml', 'price_type': '販売',
                    'supplier_id': 'supplier-demo', 'conditions': {'freight_basis': 'included',
                                                                    'currency': 'JPY'}}],
        'as_of': DEMO_DATE,
        'confirmed_by': '架空デモ担当',
    },
}

QUOTE_NAMESPACE = 'quote_snapshot'


def run(payload: dict, store) -> dict:
    """Return per-item comparisons without finalizing prices or changing quotes."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'compare')
    if action == 'compare_demo':
        _seed_demo(payload, store)
        return _compare(payload, store, simulator=True)
    if action == 'compare':
        return _compare(payload, store, simulator=False)
    raise ValidationError('action: compare / compare_demo を選択してください')


def _seed_demo(payload, store):
    if payload.get('quote_id') != 'demo-m27-quote':
        raise ValidationError('compare_demo: 架空デモの quote_id を指定してください')
    quote = store.records(QUOTE_NAMESPACE, 'demo-m27-quote')
    if not quote:
        old = demo_item(item_id='demo-m27-paint', price_type='販売', unit_price='100', unit='ml')
        old['updated_at'] = '2026-08-01'
        old['source'] = 'simulator:架空M27前回価格'
        old_version = store.add_price(old, '架空デモ担当', supplier_id='supplier-demo',
                                       valid_from='2026-08-01', transaction_conditions={'freight_basis': 'included', 'currency': 'JPY'})
        current = demo_item(item_id='demo-m27-paint', price_type='販売', unit_price='120', unit='ml')
        current['source'] = 'simulator:架空M27現行価格'
        store.add_price(current, '架空デモ担当', supplier_id='supplier-demo',
                        transaction_conditions={'freight_basis': 'included', 'currency': 'JPY'})
        store.put(QUOTE_NAMESPACE, {
            'quote_id': 'demo-m27-quote', 'confirmed_by': '架空デモ担当',
            'created_at': '2026-08-01T00:00:00+09:00', 'simulator': True,
            'lines': [{
                'quote_line_id': 'demo-m27-line', 'item_id': 'demo-m27-paint',
                'name': old['name'], 'category': old['category'], 'quantity': '1', 'unit': 'ml',
                'unit_price_snapshot': '100', 'price_type': '販売',
                'price_version_id': old_version['price_version_id'],
                'source_snapshot': old['source'], 'updated_at': '2026-08-01',
                'supplier_id': 'supplier-demo',
                'conditions': {'freight_basis': 'included', 'currency': 'JPY'}, 'line_total': '100',
            }],
        }, record_id='demo-m27-quote')


def _compare(payload, store, *, simulator):
    quote_id = text_value(payload.get('quote_id'), 'quote_id')
    basket = payload.get('basket')
    if not isinstance(basket, list) or not basket:
        raise ValidationError('basket: 比較する品目を1件以上指定してください')
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    # Explicit human confirmation identifies the comparison request; it does not approve a price.
    confirmer = approved_by(payload)
    snapshot = store.latest(QUOTE_NAMESPACE, quote_id)
    previous_lines = snapshot.get('lines')
    if not isinstance(previous_lines, list):
        raise ValidationError('quote_snapshot.lines: 見積行を確認してください')
    results = []
    for index, selection in enumerate(basket):
        if not isinstance(selection, dict):
            raise ValidationError(f'basket[{index}]: 品目条件を確認してください')
        item_id = text_value(selection.get('item_id'), 'item_id')
        unit = text_value(selection.get('unit'), 'unit')
        price_type = text_value(selection.get('price_type'), 'price_type')
        supplier_id = text_value(selection.get('supplier_id', ''), 'supplier_id') if selection.get('supplier_id', '') else ''
        conditions = selection.get('conditions', {})
        if not isinstance(conditions, dict):
            raise ValidationError('conditions: 取引条件を確認してください')
        matches = [line for line in previous_lines if isinstance(line, dict) and line.get('item_id') == item_id]
        result = {'item_id': item_id, 'status': 'comparison_unavailable'}
        if len(matches) == 1:
            previous = matches[0]
            # Missing or different identity/conditions must never be presented as a delta.
            if (previous.get('unit') == unit and previous.get('price_type') == price_type
                    and previous.get('supplier_id', '') == supplier_id
                    and previous.get('conditions', {}) == conditions):
                try:
                    current = store.get_price(item_id, price_type, as_of=as_of,
                                              supplier_id=supplier_id, unit=unit)
                except ValidationError:
                    current = None
                if current and current.get('metadata', {}).get('transaction_conditions', {}) == conditions:
                    previous_price = decimal_value(previous.get('unit_price_snapshot'), 'unit_price_snapshot')
                    current_price = decimal_value(current['item'].get('unit_price'), 'current.unit_price')
                    result = {
                        'item_id': item_id, 'status': 'comparable',
                        'previous_unit_price': str(previous_price), 'current_unit_price': str(current_price),
                        'difference': str(current_price - previous_price),
                        'previous_price_version_id': text_value(previous.get('price_version_id'), 'price_version_id'),
                        'current_price_version_id': current['price_version_id'],
                        'unit': unit, 'price_type': price_type, 'supplier_id': supplier_id,
                        'conditions': conditions,
                    }
                else:
                    result['reason'] = '現行価格がないか取引条件が一致しません'
            else:
                result['reason'] = '単位・価格区分・仕入先・取引条件が一致しません'
        else:
            result['reason'] = '前回見積に同一品目がないか、複数あります'
        results.append(result)
    return {
        'status': 'compared', 'quote_id': quote_id, 'comparisons': results,
        'confirmed_by': confirmer, 'simulator': simulator or bool(snapshot.get('simulator')),
        'price_finalized': False,
        'notice': '差額は参考表示です。採用価格は人が確認するまで確定しません。',
    }
