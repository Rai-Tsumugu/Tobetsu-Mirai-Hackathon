"""M23: compare quoted material quantities with recorded usage."""

from datetime import datetime, timezone
from uuid import uuid4

from .core import ValidationError, approved_by, decimal_value, text_value


SPEC = {
    'idea_id': 'M23',
    'title': '見積量と実使用量の比較',
    'description': '見積スナップショットの数量と実使用量を比較し、理由付きで別記録します。',
    'defaults': {
        'action': 'record_demo',
        'quote_id': 'demo-m23-quote',
        'quote_line_id': 'demo-m23-line',
        'actual_qty': '12.5',
        'reason': 'simulator:架空デモ作業で一部を使い切らなかった',
        'confirmed_by': '架空デモ担当',
    },
}

QUOTE_NAMESPACE = 'quote_snapshot'
USAGE_NAMESPACE = 'item_usage'


def run(payload: dict, store) -> dict:
    """Record an actual quantity against a saved quote line or list records."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'record')
    if action == 'record_demo':
        _ensure_demo_quote(store)
        return _record(payload, store, simulator=True)
    if action == 'record':
        return _record(payload, store, simulator=False)
    if action == 'list':
        return _list(payload, store)
    raise ValidationError('action: record_demo / record / list を選択してください')


def _ensure_demo_quote(store):
    """Create a clearly fictional quote only for the explicit demo action."""
    if store.records(QUOTE_NAMESPACE, 'demo-m23-quote'):
        return
    snapshot = {
        'quote_id': 'demo-m23-quote',
        'lines': [{
            'quote_line_id': 'demo-m23-line', 'item_id': 'demo-m23-material',
            'name': '架空デモ材料', 'category': '消耗品', 'quantity': '15',
            'unit': 'ml', 'unit_price_snapshot': '0', 'price_type': '販売',
            'price_version_id': 'simulator:no-price-seeded',
            'source_snapshot': 'simulator:架空見積スナップショット',
            'updated_at': '2026-10-11T00:00:00+09:00', 'supplier_id': '',
            'conditions': {}, 'line_total': '0',
        }],
        'confirmed_by': '架空デモ担当',
        'created_at': '2026-10-11T00:00:00+09:00',
        'simulator': True,
    }
    store.put(QUOTE_NAMESPACE, snapshot, record_id='demo-m23-quote')


def _record(payload, store, simulator):
    quote_id = text_value(payload.get('quote_id'), 'quote_id')
    quote_line_id = text_value(payload.get('quote_line_id'), 'quote_line_id')
    actual_qty = decimal_value(payload.get('actual_qty'), 'actual_qty')
    reason = text_value(payload.get('reason'), 'reason')
    confirmer = approved_by(payload)

    snapshot = store.latest(QUOTE_NAMESPACE, quote_id)
    lines = snapshot.get('lines')
    if not isinstance(lines, list):
        raise ValidationError('quote_snapshot.lines: 見積行を確認してください')
    matches = [line for line in lines if isinstance(line, dict)
               and line.get('quote_line_id') == quote_line_id]
    if len(matches) != 1:
        raise ValidationError('quote_line_id: 見積スナップショット内の一意な行を指定してください')
    line = matches[0]
    estimated_qty = decimal_value(line.get('quantity'), 'quote_snapshot.quantity')
    unit = text_value(line.get('unit'), 'quote_snapshot.unit')
    difference = actual_qty - estimated_qty
    recorded_at = datetime.now(timezone.utc).isoformat()
    record = {
        'quote_id': quote_id,
        'quote_line_id': quote_line_id,
        'item_id': text_value(line.get('item_id'), 'quote_snapshot.item_id'),
        'estimated_qty': str(estimated_qty),
        'actual_qty': str(actual_qty),
        'difference': str(difference),
        'unit': unit,
        'reason': reason,
        'confirmed_by': confirmer,
        'recorded_at': recorded_at,
        'simulator': simulator or bool(snapshot.get('simulator'))
                      or str(snapshot.get('source', '')).startswith('simulator:'),
    }
    saved = store.put(USAGE_NAMESPACE, record, record_id=uuid4().hex)
    return {
        'status': 'saved', 'item_usage': saved,
        'comparison': {
            'estimated_qty': str(estimated_qty), 'actual_qty': str(actual_qty),
            'difference': str(difference), 'unit': unit,
        },
        'simulator': record['simulator'],
        'notice': '実使用量を別記録しました。見積数量・標準量・価格は変更していません。',
    }


def _list(payload, store):
    quote_id = payload.get('quote_id')
    quote_line_id = payload.get('quote_line_id')
    if quote_id is not None:
        quote_id = text_value(quote_id, 'quote_id')
    if quote_line_id is not None:
        quote_line_id = text_value(quote_line_id, 'quote_line_id')
    rows = [row for row in store.records(USAGE_NAMESPACE)
            if (quote_id is None or row.get('quote_id') == quote_id)
            and (quote_line_id is None or row.get('quote_line_id') == quote_line_id)]
    return {'item_usages': rows, 'simulator': any(row.get('simulator') for row in rows)}
