"""M20: propose material usage ranges from a human-approved area band."""

from decimal import Decimal, localcontext

from .core import DEMO_DATE, ValidationError, date_value, decimal_value, text_value


SPEC = {
    'idea_id': 'M20',
    'title': '面積帯の使用量目安',
    'description': '工場承認済みの面積帯ごとの使用量幅と、同単位の承認済み価格から候補幅を表示します。',
    'defaults': {
        'action': 'record', 'item_id': 'demo-m20-paint', 'area_band': '架空の小面積',
        'low_qty': '10', 'typical_qty': '15', 'high_qty': '20', 'unit': 'ml',
        'evidence': 'simulator:架空デモ用の仮定値', 'approved_by': '架空デモ担当',
        'reason': '架空デモデータ',
    },
}

NAMESPACE = 'usage_band'


def run(payload: dict, store) -> dict:
    """Record an approved usage band, list bands, or estimate a price range.

    Estimates remain proposals for human review. This module never seeds an item
    or price while reading or estimating.
    """
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'estimate')
    if action == 'record':
        _check_keys(payload, {'action', 'item_id', 'area_band', 'low_qty', 'typical_qty',
                              'high_qty', 'unit', 'evidence', 'approved_by', 'reason'})
        return _record(payload, store)
    if action == 'list':
        _check_keys(payload, {'action', 'item_id', 'area_band'})
        return _list(payload, store)
    if action == 'estimate':
        _check_keys(payload, {'action', 'item_id', 'area_band', 'price_type', 'as_of'})
        return _estimate(payload, store)
    raise ValidationError('action: record / list / estimate を選択してください')


def _check_keys(payload, allowed):
    if set(payload) - allowed:
        raise ValidationError('payload: 指定できない項目があります')


def _band_key(item_id, area_band):
    return f'{item_id}:{area_band}'


def _record(payload, store):
    item_id = text_value(payload.get('item_id'), 'item_id')
    area_band = text_value(payload.get('area_band'), 'area_band')
    unit = text_value(payload.get('unit'), 'unit')
    low_qty = decimal_value(payload.get('low_qty'), 'low_qty')
    typical_qty = decimal_value(payload.get('typical_qty'), 'typical_qty')
    high_qty = decimal_value(payload.get('high_qty'), 'high_qty')
    if not low_qty <= typical_qty <= high_qty:
        raise ValidationError('数量帯: low_qty <= typical_qty <= high_qty の順にしてください')
    evidence = text_value(payload.get('evidence'), 'evidence')
    confirmer = text_value(payload.get('approved_by'), 'approved_by')
    reason = text_value(payload.get('reason'), 'reason')
    record = {
        'item_id': item_id, 'area_band': area_band,
        'low_qty': str(low_qty), 'typical_qty': str(typical_qty), 'high_qty': str(high_qty),
        'unit': unit, 'evidence': evidence, 'approved_by': confirmer,
        'status': 'approved', 'reason': reason,
    }
    saved = store.put(NAMESPACE, record, record_id=_band_key(item_id, area_band))
    return {'status': 'saved', 'usage_band': saved, 'simulator': evidence.startswith('simulator:')}


def _list(payload, store):
    item_id = payload.get('item_id')
    area_band = payload.get('area_band')
    if item_id is not None:
        item_id = text_value(item_id, 'item_id')
    if area_band is not None:
        area_band = text_value(area_band, 'area_band')
    bands = {}
    for record in store.records(NAMESPACE):
        if item_id is not None and record['item_id'] != item_id:
            continue
        if area_band is not None and record['area_band'] != area_band:
            continue
        bands[(record['item_id'], record['area_band'])] = record
    rows = list(bands.values())
    rows.sort(key=lambda row: (row['item_id'], row['area_band']))
    return {'usage_bands': rows, 'simulator': any(row['evidence'].startswith('simulator:') for row in rows)}


def _estimate(payload, store):
    item_id = text_value(payload.get('item_id'), 'item_id')
    area_band = text_value(payload.get('area_band'), 'area_band')
    price_type = payload.get('price_type', '販売')
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    candidates = [row for row in store.records(NAMESPACE)
                  if row['item_id'] == item_id and row['area_band'] == area_band]
    band = candidates[-1] if candidates else None
    if band is None or band.get('status') != 'approved' or not band.get('approved_by'):
        return _unknown(item_id, area_band, '承認済みの使用量目安がありません')

    # Validate persisted data too; old or manually inserted records cannot bypass checks.
    try:
        quantities = [decimal_value(band.get(field), field)
                      for field in ('low_qty', 'typical_qty', 'high_qty')]
        if not quantities[0] <= quantities[1] <= quantities[2]:
            raise ValidationError('数量帯の順序が不正です')
        unit = text_value(band.get('unit'), 'unit')
        evidence = text_value(band.get('evidence'), 'evidence')
    except ValidationError:
        return _unknown(item_id, area_band, '使用量の単位・数量・根拠を確認してください')

    try:
        version = store.get_price(item_id, price_type, as_of=as_of, unit=unit)
    except ValidationError:
        return _unknown(item_id, area_band, '同じ単位の承認済み価格がありません', unit=unit)
    unit_price = Decimal(version['item']['unit_price'])
    with localcontext() as context:
        context.prec = 60
        amounts = [qty * unit_price for qty in quantities]
    return {
        'status': 'needs_human_confirmation', 'item_id': item_id,
        'area_band': area_band, 'quantity': {
            'low': str(quantities[0]), 'typical': str(quantities[1]), 'high': str(quantities[2]),
            'unit': unit, 'evidence': evidence, 'approved_by': band['approved_by'],
        },
        'price': {'unit_price': version['item']['unit_price'], 'unit': unit,
                  'price_type': price_type, 'price_version_id': version['price_version_id']},
        'candidate_amount': {'low': str(amounts[0]), 'typical': str(amounts[1]),
                             'high': str(amounts[2]), 'currency': 'JPY'},
        'unknowns': [], 'simulator': bool(evidence.startswith('simulator:')
                                         or version['item']['source'].startswith('simulator:')),
    }


def _unknown(item_id, area_band, reason, unit=None):
    return {'status': 'needs_human_input', 'item_id': item_id, 'area_band': area_band,
            'quantity': None, 'unit': unit, 'candidate_amount': None,
            'unknowns': [reason], 'simulator': False}
