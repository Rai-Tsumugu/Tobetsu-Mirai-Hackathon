"""M08: preview and append a human-confirmed price change."""

from decimal import Decimal, localcontext

from .core import DEMO_DATE, PRICE_TYPES, ValidationError, approved_by, date_value, decimal_value, text_value


SPEC = {
    'idea_id': 'M08',
    'title': 'クイック価格変更',
    'description': '品目と価格区分を検索し、差分を確認してから新しい価格版を追記します。',
    'defaults': {
        'action': 'preview_change',
        'item_id': 'demo-paint',
        'price_type': '販売',
        'new_price': '130',
        'reason': '架空デモ価格の見直し',
        'source': 'simulator:架空値、架空価格票で確認',
        'checked_at': DEMO_DATE,
        'confirmed_by': '架空デモ担当',
    },
}


def run(payload: dict, store) -> dict:
    """Search, preview, or explicitly confirm a price revision.

    A preview is read-only. ``confirm_change`` repeats the validation and
    requires the version seen in the preview, preventing a stale confirmation
    from replacing a price changed by another user in the meantime.
    """
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'preview_change')
    if action == 'search_items':
        return _search_items(payload, store)
    if action in ('preview_change', 'confirm_change'):
        preview = _preview_change(payload, store)
        if action == 'preview_change':
            return {key: value for key, value in preview.items() if key != '_values'}
        expected_version_id = text_value(payload.get('expected_price_version_id'), 'expected_price_version_id')
        if expected_version_id != preview['current_price_version_id']:
            raise ValidationError('価格がプレビュー後に変更されています: 再確認してください')
        values = preview['_values']
        with store.transaction():
            # Recheck after entering the transaction to keep the append based on
            # the exact version a human reviewed.
            latest_preview = _preview_change(payload, store)
            if latest_preview['current_price_version_id'] != expected_version_id:
                raise ValidationError('価格がプレビュー後に変更されています: 再確認してください')
            version = store.add_price(
                values['item'], values['confirmed_by'],
                supplier_id=values['supplier_id'],
                valid_from=values['checked_at'],
                reason=values['reason'],
                checked_at=values['checked_at'],
            )
        return _saved_result(latest_preview, version)
    raise ValidationError('action: search_items / preview_change / confirm_change を選択してください')


def _search_items(payload: dict, store) -> dict:
    query = text_value(payload.get('query'), 'query').casefold()
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    price_type = payload.get('price_type')
    if price_type is not None and price_type not in PRICE_TYPES:
        raise ValidationError('price_type: 仕入または販売を選択してください')

    # Return one latest approved record per item, price type, and supplier.
    latest_by_key = {}
    for version in store.price_versions():
        item = version['item']
        if version['status'] != 'approved' or version['valid_from'] > as_of:
            continue
        if price_type is not None and item['price_type'] != price_type:
            continue
        if query not in item['item_id'].casefold() and query not in item['name'].casefold():
            continue
        key = (item['item_id'], item['price_type'], version['supplier_id'])
        previous = latest_by_key.get(key)
        if previous is None or version['valid_from'] >= previous['valid_from']:
            latest_by_key[key] = version

    candidates = []
    for version in latest_by_key.values():
        item = version['item']
        candidates.append({
            'item': item,
            'price_type': item['price_type'],
            'supplier_id': version['supplier_id'],
            'price_version_id': version['price_version_id'],
            'valid_from': version['valid_from'],
            'valid_until': version['valid_until'],
        })
    candidates.sort(key=lambda candidate: (
        candidate['item']['name'], candidate['item']['item_id'],
        candidate['price_type'], candidate['supplier_id'],
    ))
    return {
        'query': text_value(payload.get('query'), 'query'),
        'as_of': as_of,
        'candidates': candidates,
        'items': [candidate['item'] for candidate in candidates],
        'simulator': True,
    }


def _preview_change(payload: dict, store) -> dict:
    item_id = text_value(payload.get('item_id'), 'item_id')
    price_type = text_value(payload.get('price_type'), 'price_type')
    if price_type not in PRICE_TYPES:
        raise ValidationError('price_type: 仕入または販売を選択してください')
    supplier_id = payload.get('supplier_id')
    if supplier_id is not None and supplier_id != '':
        supplier_id = text_value(supplier_id, 'supplier_id')
    reason = text_value(payload.get('reason'), 'reason')
    source = text_value(payload.get('source'), 'source')
    checked_at = date_value(payload.get('checked_at'), 'checked_at').isoformat()
    confirmer = approved_by(payload)
    new_price = decimal_value(payload.get('new_price'), 'new_price', positive=True)

    all_versions = [version for version in store.price_versions(item_id, price_type, supplier_id)
                    if version['status'] == 'approved']
    suppliers = {version['supplier_id'] for version in all_versions}
    if supplier_id is None and len(suppliers) > 1:
        raise ValidationError('supplier_id: 仕入先の選択が必要です')
    if all_versions:
        latest_version = max(enumerate(all_versions), key=lambda pair: (pair[1]['valid_from'], pair[0]))[1]
        if checked_at < latest_version['valid_from']:
            raise ValidationError('checked_at: 現行価格の開始日以降を指定してください')
    versions = [version for version in all_versions if version['valid_from'] <= checked_at]
    if not versions:
        raise ValidationError('価格未確認: 変更対象の承認済み価格がありません')
    current = max(enumerate(versions), key=lambda pair: (pair[1]['valid_from'], pair[0]))[1]

    old_price = decimal_value(current['item']['unit_price'], 'unit_price')
    with localcontext() as context:
        context.prec = 80
        difference = new_price - old_price
    new_item = dict(current['item'])
    new_item.update(unit_price=str(new_price), source=source, updated_at=checked_at)
    preview = {
        'status': 'preview',
        'item': new_item,
        'items': [new_item],
        'item_id': item_id,
        'price_type': price_type,
        'supplier_id': current['supplier_id'],
        'unit': current['item']['unit'],
        'current_price': str(old_price),
        'new_price': str(new_price),
        'difference': str(difference),
        'direction': 'increase' if difference > 0 else 'decrease' if difference < 0 else 'unchanged',
        'reason': reason,
        'source': source,
        'checked_at': checked_at,
        'confirmed_by': confirmer,
        'current_price_version_id': current['price_version_id'],
        'requires_confirmation': True,
        'simulator': current['item']['source'].startswith('simulator:') or source.startswith('simulator:'),
        '_values': {
            'item': new_item,
            'supplier_id': current['supplier_id'],
            'checked_at': checked_at,
            'reason': reason,
            'confirmed_by': confirmer,
        },
    }
    return preview


def _saved_result(preview: dict, version: dict) -> dict:
    item = version['item']
    result = {key: value for key, value in preview.items() if key != '_values'}
    result.update({
        'status': 'saved',
        'item': item,
        'items': [item],
        'price_version_id': version['price_version_id'],
        'previous_price_version_id': preview['current_price_version_id'],
        'requires_confirmation': False,
        'confirmed_by': version['confirmed_by'],
    })
    return result
