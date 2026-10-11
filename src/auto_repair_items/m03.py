"""Manage separate purchase and customer-facing prices for one item."""

from .core import (
    DEMO_DATE,
    ValidationError,
    approved_by,
    date_value,
    decimal_value,
    text_value,
    validate_item,
)


SPEC = {
    'idea_id': 'M03',
    'title': '仕入・販売の二列価格',
    'description': '同一品目の仕入価格と販売価格を独立して保存・参照します。販売価格が未登録なら見積利用を停止し、仕入価格から販売価格を自動計算しません。',
    'defaults': {
        'action': 'get_price',
        'item_id': 'demo-paint',
        'price_type': '販売',
        'as_of': DEMO_DATE,
    },
}


def run(payload: dict, store) -> dict:
    """Save one confirmed price or retrieve a valid price version.

    Save payloads use ``action='save_price'`` and include the common item
    fields plus ``confirmed_by``. Retrieval payloads use ``action='get_price'``.
    The default retrieval expects ``seed_demo(store)`` to have been called.
    """
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')

    action = payload.get('action', 'get_price')
    if action == 'save_price':
        return _save_price(payload, store)
    if action == 'get_price':
        return _get_price(payload, store)
    raise ValidationError('action: save_price または get_price を選択してください')


def _save_price(payload: dict, store) -> dict:
    item = validate_item(payload.get('item'))
    confirmer = approved_by(payload)
    reason = text_value(payload.get('reason', '価格登録'), 'reason')
    supplier_id = payload.get('supplier_id', '')
    if not isinstance(supplier_id, str):
        raise ValidationError('supplier_id: 文字列を入力してください')
    valid_from = date_value(payload.get('valid_from', item['updated_at']), 'valid_from').isoformat()
    valid_until = payload.get('valid_until')
    if valid_until is not None:
        valid_until = date_value(valid_until, 'valid_until').isoformat()
    currency = text_value(payload.get('currency', 'JPY'), 'currency').upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise ValidationError('currency: 3文字の通貨コードを入力してください')

    version = store.add_price(
        item,
        confirmer,
        supplier_id=supplier_id.strip(),
        valid_from=valid_from,
        valid_until=valid_until,
        status=payload.get('status', 'approved'),
        reason=reason,
        currency=currency,
    )
    return {
        'item': version['item'],
        'price_version_id': version['price_version_id'],
        'confirmed_by': version['confirmed_by'],
        'valid_from': version['valid_from'],
        'valid_until': version['valid_until'],
        'status': version['status'],
        'reason': version['reason'],
        'currency': version['metadata']['currency'],
    }


def _get_price(payload: dict, store) -> dict:
    item_id = text_value(payload.get('item_id'), 'item_id')
    price_type = payload.get('price_type', '販売')
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    supplier_id = payload.get('supplier_id')
    unit = payload.get('unit')
    if supplier_id is not None:
        supplier_id = text_value(supplier_id, 'supplier_id')
    if unit is not None:
        unit = text_value(unit, 'unit')

    version = store.get_price(
        item_id,
        price_type,
        as_of=as_of,
        supplier_id=supplier_id,
        unit=unit,
    )
    item = dict(version['item'])
    # The price returned is the stored, approved snapshot. No markup is applied.
    item['unit_price'] = str(decimal_value(item['unit_price'], 'unit_price'))
    return {
        'item': item,
        'price_version_id': version['price_version_id'],
        'confirmed_by': version['confirmed_by'],
        'valid_from': version['valid_from'],
        'valid_until': version['valid_until'],
        'status': version['status'],
        'reason': version['reason'],
        'currency': version['metadata'].get('currency', 'JPY'),
    }
