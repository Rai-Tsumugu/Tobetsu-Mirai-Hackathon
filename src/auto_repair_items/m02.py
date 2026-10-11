"""M02: convert approved package prices and quantities to a base unit."""

from decimal import Decimal, localcontext

from .core import DEMO_DATE, ValidationError, approved_by, decimal_value, demo_item, text_value


SPEC = {
    'idea_id': 'M02',
    'title': '容量・入数単位変換',
    'description': '根拠を確認した包装単位の価格と数量を基準単位へ換算します。',
    'defaults': {
        'item_id': 'demo-paint',
        'source_unit': 'ml',
        'base_unit': 'ml',
        'factor': '1',
        'evidence': 'simulator:架空値、同一単位のデモ換算',
        'quantity': '1',
        'price_type': '仕入',
        'confirmed_by': '架空デモ担当',
        'as_of': DEMO_DATE,
    },
}

# These units share dimensions. Packaging units (箱, 缶, セット) are counted
# as discrete units; the explicit factor records how many base units they hold.
_UNIT_DIMENSIONS = {
    '個': 'count', '本': 'count', '缶': 'count', '箱': 'count', 'セット': 'count',
    'ml': 'volume', 'L': 'volume', 'g': 'mass', 'kg': 'mass',
}


def _conversion_id(item_id, source_unit, base_unit):
    return f'{item_id}|{source_unit}|{base_unit}'


def _validate_units(source_unit, base_unit):
    if source_unit not in _UNIT_DIMENSIONS or base_unit not in _UNIT_DIMENSIONS:
        raise ValidationError('unit: 対応する単位を選択してください')
    if _UNIT_DIMENSIONS[source_unit] != _UNIT_DIMENSIONS[base_unit]:
        raise ValidationError('unit: 次元が異なる単位は換算できません')


def run(payload: dict, store) -> dict:
    """Return an approved price and quantity expressed in the base unit.

    ``factor`` means the number of base units in one source unit. The stored
    approved price must be denominated in ``source_unit``; no caller-provided
    price can bypass Store approval and expiry checks.
    """
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    item_id = text_value(payload.get('item_id'), 'item_id')
    source_unit = text_value(payload.get('source_unit'), 'source_unit')
    base_unit = text_value(payload.get('base_unit'), 'base_unit')
    _validate_units(source_unit, base_unit)
    factor = decimal_value(payload.get('factor'), 'factor', positive=True)
    if source_unit == base_unit and factor != Decimal('1'):
        raise ValidationError('factor: 同一単位の換算係数は1です')
    evidence = text_value(payload.get('evidence'), 'evidence')
    quantity = decimal_value(payload.get('quantity'), 'quantity')
    confirmed_by = approved_by(payload)
    price_type = text_value(payload.get('price_type', '販売'), 'price_type')
    as_of = text_value(payload.get('as_of', DEMO_DATE), 'as_of')
    conversion_id = _conversion_id(item_id, source_unit, base_unit)

    # Fail closed if a conversion was previously registered with different
    # terms. The caller must explicitly confirm each new factor/evidence pair.
    existing = [r for r in store.records('unit_conversion', conversion_id)]
    if existing:
        previous = existing[-1]
        if previous['factor'] != str(factor) or previous['evidence'] != evidence:
            raise ValidationError('換算根拠が登録済み内容と異なります: 再確認してください')
    version = store.get_price(item_id, price_type, as_of=as_of, unit=source_unit)
    source_item = version['item']
    source_price = decimal_value(source_item['unit_price'], 'unit_price')
    with localcontext() as context:
        # decimal_value caps inputs at 28 significant digits; 60 digits leaves
        # room for exact products and lets us detect a repeating division.
        context.prec = 60
        normalized_quantity = quantity * factor
        normalized_price = source_price / factor
    with localcontext() as context:
        context.prec = 60
        exact_price = normalized_price * factor == source_price
    if not exact_price:
        raise ValidationError('単価を有限桁で正確に表せません: 丸め規則を確認してください')
    normalized_item = dict(source_item)
    normalized_item.update(unit=base_unit, unit_price=str(normalized_price))

    if not existing:
        with store.transaction():
            store.put('unit_conversion', {
                'item_id': item_id,
                'source_unit': source_unit,
                'base_unit': base_unit,
                'factor': str(factor),
                'evidence': evidence,
                'confirmed_by': confirmed_by,
            }, record_id=conversion_id)

    return {
        'item': normalized_item,
        'items': [normalized_item],
        'source_quantity': str(quantity),
        'source_unit': source_unit,
        'quantity': str(normalized_quantity),
        'unit': base_unit,
        'source_unit_price': str(source_price),
        'unit_price': str(normalized_price),
        'price_type': price_type,
        'price_version_id': version['price_version_id'],
        'conversion': {
            'factor': str(factor),
            'evidence': evidence,
            'confirmed_by': confirmed_by,
        },
    }
