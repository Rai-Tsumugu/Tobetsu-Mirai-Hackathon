"""M14: show how long ago a person checked a price and its source date."""

from datetime import date

from .core import DEMO_DATE, ValidationError, date_value, demo_item, text_value


SPEC = {
    'idea_id': 'M14',
    'title': '最終確認からの経過表示',
    'description': '価格を最後に人が確認した日と経過日数を、出所の更新日と分けて表示します。',
    'defaults': {
        'item_id': 'demo-m14-paint',
        'price_type': '仕入',
        'as_of': DEMO_DATE,
    },
}


def run(payload: dict, store) -> dict:
    """Return freshness metadata; this operation never edits a price."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    if set(payload) - {'item_id', 'price_type', 'as_of'}:
        raise ValidationError('payload: item_id、price_type、as_ofだけ指定できます')

    item_id = text_value(payload.get('item_id'), 'item_id')
    price_type = payload.get('price_type', '仕入')
    if price_type not in ('仕入', '販売'):
        raise ValidationError('price_type: 選択値を確認してください')
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of')
    versions = store.price_versions(item_id, price_type)
    if not versions:
        if item_id != SPEC['defaults']['item_id']:
            raise ValidationError('価格未確認: 対象価格がありません')
        # The fictional seed marks its human check explicitly. item.updated_at
        # remains the separate source date.
        item = demo_item(item_id=item_id, price_type=price_type, unit_price='80')
        store.add_price(item, '架空デモ担当', checked_at=DEMO_DATE,
                        source_updated_at=DEMO_DATE, simulator=True)
        versions = store.price_versions(item_id, price_type)

    version = versions[-1]
    metadata = version.get('metadata') or {}
    checked_at = metadata.get('checked_at')
    source_updated_at = metadata.get('source_updated_at') or version['item'].get('updated_at')
    checked_date = _optional_date(checked_at, 'checked_at')
    source_date = _optional_date(source_updated_at, 'source_updated_at')
    for field, parsed in (('checked_at', checked_date), ('source_updated_at', source_date)):
        if parsed is not None and parsed > as_of:
            raise ValidationError(f'{field}: 基準日より未来の日付です')

    elapsed_days = (as_of - checked_date).days if checked_date is not None else None
    return {
        'status': '確認済み' if checked_date is not None else '未確認',
        'item_id': item_id,
        'price_type': price_type,
        'human_checked_at': checked_date.isoformat() if checked_date else None,
        'elapsed_days': elapsed_days,
        'source_updated_at': source_date.isoformat() if source_date else None,
        'as_of': as_of.isoformat(),
        'message': (f'最終人確認から{elapsed_days}日経過' if elapsed_days is not None
                    else '最終人確認日は未確認です'),
        'simulator': bool(metadata.get('simulator', False)),
    }


def _optional_date(value, field):
    if value is None:
        return None
    return date_value(value, field)
