"""M06: append price changes as events linked to immutable price versions."""

from datetime import date, datetime

from .core import (
    DEMO_DATE,
    ValidationError,
    approved_by,
    date_value,
    demo_item,
    text_value,
    validate_item,
)


SPEC = {
    'idea_id': 'M06',
    'title': '価格イベント台帳',
    'description': '価格版を上書きせず、変更理由・出所・担当者とともに追記して履歴化します。',
    'defaults': {
        'action': 'record_event',
        'item': demo_item(price_type='販売', unit_price='125'),
        'event_type': 'increase',
        'reason': '架空デモの価格改定',
        'source': 'simulator:架空値',
        'confirmed_by': '架空デモ担当',
        'occurred_at': DEMO_DATE,
    },
}

_EVENT_TYPES = ('initial', 'increase', 'correction', 'condition_change')


def run(payload: dict, store) -> dict:
    """Record a price version and its event, or list an item's event history."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'record_event')
    if action == 'record_event':
        return _record_event(payload, store)
    if action == 'list_events':
        item_id = text_value(payload.get('item_id'), 'item_id')
        events = store.records('price_event', item_id)
        return {
            'item_id': item_id,
            'events': [{key: value for key, value in event.items() if key != 'record_id'}
                       for event in events],
            'simulator': True,
        }
    raise ValidationError('action: record_event または list_events を選択してください')


def _record_event(payload: dict, store) -> dict:
    item = validate_item(payload.get('item'))
    event_type = text_value(payload.get('event_type'), 'event_type')
    if event_type not in _EVENT_TYPES:
        raise ValidationError('event_type: initial / increase / correction / condition_change を選択してください')
    reason = text_value(payload.get('reason'), 'reason')
    source = text_value(payload.get('source', item['source']), 'source')
    actor = approved_by(payload)
    supplier_id = payload.get('supplier_id', '')
    if supplier_id is None:
        supplier_id = ''
    elif not isinstance(supplier_id, str):
        raise ValidationError('supplier_id: 文字列を入力してください')
    supplier_id = supplier_id.strip()
    status = payload.get('status', 'approved')
    if status not in ('approved', 'pending'):
        raise ValidationError('status: approved または pending を指定してください')

    # Keep the common items contract's source aligned with the event evidence.
    item['source'] = source
    occurred_at = _occurred_at(payload.get('occurred_at', item['updated_at']))
    previous = store.price_versions(
        item_id=item['item_id'], price_type=item['price_type'], supplier_id=supplier_id)
    old_version = previous[-1]['price_version_id'] if previous else None
    if old_version is None and event_type != 'initial':
        raise ValidationError('event_type: 初回登録は initial を選択してください')
    if old_version is not None and event_type == 'initial':
        raise ValidationError('event_type: 既存価格の変更には別のイベント種別を選択してください')

    valid_from = date_value(payload.get('valid_from', item['updated_at']), 'valid_from').isoformat()
    valid_until = payload.get('valid_until')
    with store.transaction():
        version = store.add_price(
            item,
            actor,
            supplier_id=supplier_id,
            valid_from=valid_from,
            valid_until=valid_until,
            status=status,
            reason=reason,
        )
        event = {
            'item_id': item['item_id'],
            'old_version': old_version,
            'new_version': version['price_version_id'],
            'event_type': event_type,
            'reason': reason,
            'source': source,
            'actor': actor,
            'occurred_at': occurred_at,
            'status': status,
        }
        saved_event = store.put('price_event', event, record_id=item['item_id'])

        # Return the currently approved, effective price only. A pending event
        # can be recorded while the last confirmed price remains available.
        current_items = []
        try:
            current = store.get_price(
                item['item_id'], item['price_type'], as_of=version['valid_from'],
                supplier_id=supplier_id)
        except ValidationError:
            if status == 'approved':
                raise
        else:
            current_items = [current['item']]

    return {
        'event': {key: value for key, value in saved_event.items() if key != 'record_id'},
        'price_version': version,
        'items': current_items,
        'simulator': True,
        'notice': '価格は架空デモ値です。承認済みの価格だけを items に返しています。',
    }


def _occurred_at(value) -> str:
    value = text_value(value, 'occurred_at')
    try:
        if 'T' not in value and ' ' not in value:
            return date.fromisoformat(value).isoformat()
        return datetime.fromisoformat(value.replace('Z', '+00:00')).isoformat()
    except ValueError:
        raise ValidationError('occurred_at: ISO形式の日付または日時が必要です') from None
