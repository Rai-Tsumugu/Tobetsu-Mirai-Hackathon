"""M07: register one item price and search the approved item list."""

from .core import (
    DEMO_DATE,
    ITEM_FIELDS,
    ValidationError,
    approved_by,
    date_value,
    text_value,
    validate_item,
)


SPEC = {
    'idea_id': 'M07',
    'title': '単品価格入力フォーム',
    'description': '品目と価格を一件ずつ確認者付きで登録し、承認済みの有効な品目価格を検索・一覧表示します。',
    'defaults': {
        'action': 'register',
        'item_id': 'demo-m07-brake-pad',
        'name': '架空サンプルブレーキパッド',
        'category': '部品',
        'unit': '個',
        'unit_price': '2400',
        'price_type': '販売',
        'source': 'simulator:架空値',
        'updated_at': DEMO_DATE,
        'confirmed_by': '架空デモ担当',
        'reason': '単品価格の初回確認',
        'as_of': DEMO_DATE,
        'query': '',
        'category_filter': '',
        'price_type_filter': '',
    },
}


def run(payload: dict, store) -> dict:
    """Register one confirmed price or search the active approved catalog."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')

    action = payload.get('action', 'register')
    if action == 'register':
        return _register(payload, store)
    if action in ('search', 'list'):
        return _search(payload, store)
    raise ValidationError('action: register、search、list のいずれかを指定してください')


def _register(payload: dict, store) -> dict:
    # Accept both the flat form shown by SPEC and an explicit common-item object.
    item_input = payload.get('item', payload)
    item = validate_item(item_input)
    confirmer = approved_by(payload)
    reason = text_value(payload.get('reason', '単品価格の登録'), 'reason')
    valid_from = date_value(payload.get('valid_from', item['updated_at']), 'valid_from').isoformat()
    valid_until = payload.get('valid_until')
    if valid_until is not None and valid_until != '':
        valid_until = date_value(valid_until, 'valid_until').isoformat()
    else:
        valid_until = None

    version = store.add_price(
        item,
        confirmer,
        valid_from=valid_from,
        valid_until=valid_until,
        reason=reason,
        currency='JPY',
    )
    registered_item = {field: version['item'][field] for field in ITEM_FIELDS}
    return {
        'status': version['status'],
        'item': registered_item,
        'items': [registered_item],
        'price_version_id': version['price_version_id'],
        'confirmed_by': version['confirmed_by'],
        'reason': version['reason'],
        'valid_from': version['valid_from'],
        'valid_until': version['valid_until'],
        'currency': version['metadata']['currency'],
    }


def _search(payload: dict, store) -> dict:
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    query = _optional_text(payload.get('query', ''), 'query').casefold()
    category = _optional_text(payload.get('category_filter', ''), 'category_filter')
    price_type = _optional_text(payload.get('price_type_filter', ''), 'price_type_filter')
    if category and category not in ('部品', '塗料', '溶剤', '消耗品'):
        raise ValidationError('category_filter: 選択値を確認してください')
    if price_type and price_type not in ('仕入', '販売'):
        raise ValidationError('price_type_filter: 選択値を確認してください')

    # Keep the latest effective approved version for each item and price type.
    # The public items contract has no supplier field, so supplier-specific rows
    # are not presented as distinguishable catalog entries here.
    active_by_key = {}
    for sequence, version in enumerate(store.price_versions()):
        if version['status'] != 'approved' or version['valid_from'] > as_of:
            continue
        if version['valid_until'] is not None and as_of > version['valid_until']:
            continue
        item = version['item']
        key = (item['item_id'], item['price_type'])
        prior = active_by_key.get(key)
        rank = (version['valid_from'], sequence)
        if prior is None or rank > prior[0]:
            active_by_key[key] = (rank, item)

    items = []
    for _, item in active_by_key.values():
        if category and item['category'] != category:
            continue
        if price_type and item['price_type'] != price_type:
            continue
        searchable = ' '.join((item['item_id'], item['name'], item['source'])).casefold()
        if query and query not in searchable:
            continue
        items.append({field: item[field] for field in ITEM_FIELDS})
    items.sort(key=lambda item: (item['name'].casefold(), item['item_id'], item['price_type']))
    return {'as_of': as_of, 'count': len(items), 'items': items}


def _optional_text(value, field):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValidationError(f'{field}: 文字列を入力してください')
    return value.strip()
