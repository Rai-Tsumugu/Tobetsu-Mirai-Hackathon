"""M30: save and retrieve immutable quote-time price snapshots."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from .core import (
    DEMO_DATE, ValidationError, Store, approved_by, date_value, decimal_value,
    demo_item, price_conditions, text_value,
)


SPEC = {
    'idea_id': 'M30',
    'title': '見積時価格スナップショット',
    'description': '人が選択した承認済み単価と数量を見積時点で固定し、後から再表示します。',
    'defaults': {
        'action': 'save_demo', 'quote_id': 'demo-m30-quote',
        'as_of': DEMO_DATE, 'confirmed_by': '架空デモ担当',
        'lines': [{'item_id': 'demo-m30-paint', 'quantity': '2.5', 'unit': 'ml',
                   'price_type': '販売', 'supplier_id': '',
                   'conditions': {'freight_basis': 'included', 'currency': 'JPY',
                                  'transaction_conditions': 'simulator:架空条件'}}],
    },
}

QUOTE_NAMESPACE = 'quote_snapshot'


def run(payload: dict, store: Store) -> dict:
    """Save a quote, retrieve it by ID, or list saved quotes for redisplay."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'save')
    if action == 'save_demo':
        _seed_demo_price(store)
        return _save(payload, store, simulator=True)
    if action == 'save':
        return _save(payload, store, simulator=False)
    if action == 'get':
        quote_id = text_value(payload.get('quote_id'), 'quote_id')
        quote = store.latest(QUOTE_NAMESPACE, quote_id)
        return {'status': 'found', 'quote': quote,
                'simulator': bool(quote.get('simulator'))}
    if action == 'list':
        quotes = store.records(QUOTE_NAMESPACE)
        query = payload.get('query')
        if query is not None:
            query = text_value(query, 'query').casefold()
            quotes = [quote for quote in quotes if query in quote['quote_id'].casefold()]
        return {'status': 'listed', 'quotes': quotes,
                'simulator': any(bool(quote.get('simulator')) for quote in quotes)}
    raise ValidationError('action: save / save_demo / get / list を選択してください')


def _seed_demo_price(store):
    """Create fictional price data only after explicit save_demo selection."""
    item_id = 'demo-m30-paint'
    if store.price_versions(item_id):
        return
    item = demo_item(item_id=item_id, unit_price='120', unit='ml')
    store.add_price(item, '架空デモ担当',
                    transaction_conditions='simulator:架空条件',
                    freight_basis='included', currency='JPY')


def _save(payload, store, *, simulator):
    quote_id = text_value(payload.get('quote_id'), 'quote_id')
    if store.records(QUOTE_NAMESPACE, quote_id):
        raise ValidationError('quote_id: 保存済みです。別の見積IDを指定してください')
    confirmer = approved_by(payload)
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    selections = payload.get('lines')
    if not isinstance(selections, list) or not selections:
        raise ValidationError('lines: 見積品目を1件以上指定してください')

    lines = []
    common_items = []
    seen_line_ids = set()
    for index, selection in enumerate(selections):
        if not isinstance(selection, dict):
            raise ValidationError(f'lines[{index}]: 見積品目を確認してください')
        item_id = text_value(selection.get('item_id'), f'lines[{index}].item_id')
        quantity = decimal_value(selection.get('quantity'), f'lines[{index}].quantity', positive=True)
        unit = text_value(selection.get('unit'), f'lines[{index}].unit')
        price_type = text_value(selection.get('price_type'), f'lines[{index}].price_type')
        supplier_id = selection.get('supplier_id', '')
        if supplier_id:
            supplier_id = text_value(supplier_id, f'lines[{index}].supplier_id')
        version = store.get_price(item_id, price_type, as_of=as_of,
                                  supplier_id=supplier_id or None, unit=unit)
        item = version['item']
        conditions = price_conditions(version)
        requested_conditions = selection.get('conditions')
        if requested_conditions is not None:
            if not isinstance(requested_conditions, dict):
                raise ValidationError(f'lines[{index}].conditions: 取引条件を確認してください')
            # Compare using the same normalization as M27, including explicit JPY.
            supplied = dict(requested_conditions)
            supplied.setdefault('currency', 'JPY')
            if supplied != conditions:
                raise ValidationError(f'lines[{index}].conditions: 価格版の取引条件と一致しません')
        try:
            line_total = quantity * decimal_value(item['unit_price'], 'unit_price')
        except InvalidOperation:
            raise ValidationError(f'lines[{index}]: 金額の桁数を確認してください') from None
        if len(line_total.as_tuple().digits) > 28 or abs(line_total.as_tuple().exponent) > 12:
            raise ValidationError(f'lines[{index}]: 金額の桁数を確認してください')
        line_id = text_value(selection.get('quote_line_id', uuid4().hex),
                             f'lines[{index}].quote_line_id')
        if line_id in seen_line_ids:
            raise ValidationError('quote_line_id: 重複しています')
        seen_line_ids.add(line_id)
        lines.append({
            'quote_line_id': line_id, 'item_id': item['item_id'], 'name': item['name'],
            'category': item['category'], 'quantity': str(quantity), 'unit': item['unit'],
            'unit_price_snapshot': item['unit_price'], 'price_type': item['price_type'],
            'price_version_id': version['price_version_id'], 'source_snapshot': item['source'],
            'updated_at': item['updated_at'], 'supplier_id': version['supplier_id'],
            'conditions': conditions, 'line_total': str(line_total),
        })
        common_items.append(item)

    created_at = datetime.now(timezone.utc).isoformat()
    quote = {
        'quote_id': quote_id, 'lines': lines, 'confirmed_by': confirmer,
        'created_at': created_at, 'as_of': as_of,
        'subtotal': str(sum((Decimal(line['line_total']) for line in lines), Decimal('0'))),
        'simulator': simulator,
    }
    with store.transaction():
        # Recheck under the transaction so a repeated request never appends a version.
        if store.records(QUOTE_NAMESPACE, quote_id):
            raise ValidationError('quote_id: 保存済みです。別の見積IDを指定してください')
        store.put(QUOTE_NAMESPACE, quote, record_id=quote_id)
    return {'status': 'saved', 'quote': dict(quote, record_id=quote_id),
            'items': common_items, 'simulator': simulator}
