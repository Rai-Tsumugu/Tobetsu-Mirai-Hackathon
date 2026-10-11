"""Compare confirmed supplier purchase prices under matching terms."""

from decimal import Decimal

from .core import (
    DEMO_DATE,
    ValidationError,
    approved_by,
    date_value,
    decimal_value,
    demo_item,
    text_value,
    validate_item,
)


SPEC = {
    'idea_id': 'M04',
    'title': '仕入先別価格レコード',
    'description': '同一品目の仕入先別価格を送料・税・納期条件が一致する場合だけ比較し、選択を記録します。',
    'defaults': {
        'action': 'save_offer',
        'item': demo_item(price_type='仕入', unit_price='80'),
        'supplier_id': 'demo-supplier-a',
        'freight_basis': '送料込み',
        'freight_amount': '0',
        'tax_basis': '税別',
        'delivery_days': 2,
        'checked_at': DEMO_DATE,
        'confirmed_by': '架空デモ担当',
    },
}

_COMPARISON_FIELDS = ('freight_basis', 'freight_amount', 'tax_basis', 'delivery_days', 'currency')


def run(payload: dict, store) -> dict:
    """Save a supplier offer or compare and record a human selection.

    Prices are always purchase prices. Comparison refuses to rank offers when
    their freight, tax, delivery, or currency terms differ.
    """
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'compare_and_select')
    if action == 'save_offer':
        return _save_offer(payload, store)
    if action == 'compare_and_select':
        return _compare_and_select(payload, store)
    raise ValidationError('action: save_offer または compare_and_select を選択してください')


def _save_offer(payload: dict, store) -> dict:
    item = validate_item(payload.get('item'))
    if item['price_type'] != '仕入':
        raise ValidationError('price_type: 仕入価格のみ登録できます')
    supplier_id = text_value(payload.get('supplier_id'), 'supplier_id')
    confirmer = approved_by(payload)
    freight_basis = text_value(payload.get('freight_basis'), 'freight_basis')
    freight_amount = decimal_value(payload.get('freight_amount'), 'freight_amount')
    tax_basis = text_value(payload.get('tax_basis'), 'tax_basis')
    delivery_days = _delivery_days(payload.get('delivery_days'))
    checked_at = date_value(payload.get('checked_at', item['updated_at']), 'checked_at').isoformat()
    currency = _currency(payload.get('currency', 'JPY'))
    valid_from = date_value(payload.get('valid_from', item['updated_at']), 'valid_from').isoformat()
    valid_until = payload.get('valid_until')
    if valid_until is not None:
        valid_until = date_value(valid_until, 'valid_until').isoformat()

    version = store.add_price(
        item,
        confirmer,
        supplier_id=supplier_id,
        valid_from=valid_from,
        valid_until=valid_until,
        status=payload.get('status', 'approved'),
        reason=text_value(payload.get('reason', '仕入先価格の確認'), 'reason'),
        freight_basis=freight_basis,
        freight_amount=str(freight_amount),
        tax_basis=tax_basis,
        delivery_days=delivery_days,
        checked_at=checked_at,
        currency=currency,
    )
    return _offer_result(version)


def _compare_and_select(payload: dict, store) -> dict:
    item_id = text_value(payload.get('item_id'), 'item_id')
    unit = text_value(payload.get('unit'), 'unit')
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    supplier_ids = payload.get('supplier_ids')
    if not isinstance(supplier_ids, list) or not supplier_ids:
        raise ValidationError('supplier_ids: 比較する仕入先を1件以上指定してください')
    supplier_ids = [text_value(value, 'supplier_id') for value in supplier_ids]
    if len(set(supplier_ids)) != len(supplier_ids):
        raise ValidationError('supplier_ids: 重複を除いてください')
    selected_supplier_id = text_value(payload.get('selected_supplier_id'), 'selected_supplier_id')
    confirmer = approved_by(payload)
    reason = text_value(payload.get('reason', '仕入先を選択'), 'reason')
    if selected_supplier_id not in supplier_ids:
        raise ValidationError('selected_supplier_id: 比較候補から選択してください')

    versions = [
        store.get_price(item_id, '仕入', as_of=as_of, supplier_id=supplier_id, unit=unit)
        for supplier_id in supplier_ids
    ]
    offers = [_offer_result(version) for version in versions]
    reference = offers[0]
    for offer in offers[1:]:
        if any(offer[field] != reference[field] for field in _COMPARISON_FIELDS):
            raise ValidationError('比較条件不一致: 送料・税・納期・通貨を揃えてください')

    ranked_offers = sorted(offers, key=lambda offer: (Decimal(offer['item']['unit_price']), offer['supplier_id']))
    selected = next(offer for offer in offers if offer['supplier_id'] == selected_supplier_id)
    selection = store.put('supplier_price_selection', {
        'item_id': item_id,
        'unit': unit,
        'price_type': '仕入',
        'as_of': as_of,
        'supplier_id': selected_supplier_id,
        'price_version_id': selected['price_version_id'],
        'selected_by': confirmer,
        'reason': reason,
        'conditions': {field: selected[field] for field in _COMPARISON_FIELDS},
    })
    return {
        'item_id': item_id,
        'unit': unit,
        'price_type': '仕入',
        'as_of': as_of,
        'offers': offers,
        'ranked_supplier_ids': [offer['supplier_id'] for offer in ranked_offers],
        'selected': selected,
        'selection_record_id': selection['record_id'],
        'selected_by': confirmer,
        'reason': reason,
    }


def _offer_result(version: dict) -> dict:
    item = version['item']
    if item['price_type'] != '仕入':
        raise ValidationError('price_type: 仕入価格のみ比較できます')
    metadata = version.get('metadata', {})
    return {
        'item': dict(item, unit_price=str(decimal_value(item['unit_price'], 'unit_price'))),
        'supplier_id': text_value(version.get('supplier_id'), 'supplier_id'),
        'price_version_id': text_value(version.get('price_version_id'), 'price_version_id'),
        'freight_basis': text_value(metadata.get('freight_basis'), 'freight_basis'),
        'freight_amount': str(decimal_value(metadata.get('freight_amount'), 'freight_amount')),
        'tax_basis': text_value(metadata.get('tax_basis'), 'tax_basis'),
        'delivery_days': _delivery_days(metadata.get('delivery_days')),
        'currency': _currency(metadata.get('currency', 'JPY')),
        'checked_at': date_value(metadata.get('checked_at'), 'checked_at').isoformat(),
        'source': item['source'],
        'valid_from': version['valid_from'],
        'valid_until': version['valid_until'],
        'status': version['status'],
    }


def _delivery_days(value) -> int:
    days = decimal_value(value, 'delivery_days')
    if days != days.to_integral_value():
        raise ValidationError('delivery_days: 0以上の整数を入力してください')
    return int(days)


def _currency(value) -> str:
    currency = text_value(value, 'currency').upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise ValidationError('currency: 3文字の通貨コードを入力してください')
    return currency
