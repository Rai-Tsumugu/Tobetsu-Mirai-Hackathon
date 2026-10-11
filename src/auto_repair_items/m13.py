"""M13: stage fictional, locally supplied wholesaler JSON offers."""

from datetime import datetime, timezone

from .core import DEMO_DATE, ValidationError, approved_by, date_value, decimal_value, text_value
from .importing import approve_rows, stage_rows


SPEC = {
    'idea_id': 'M13',
    'title': '卸提供JSONコネクタ',
    'description': '利用許諾と品番対応を確認したローカルJSON fixtureから仕入候補を作り、人の承認後だけ保存します。実API未接続のSimulatorです。',
    'defaults': {
        'action': 'sample',
        'confirmed_by': '架空デモ担当',
    },
}

_DEMO_FEED = {
    'mode': 'fixture',
    'source': 'simulator:架空卸fixture',
    'terms_status': 'approved',
    'schema_version': '1',
    'offers': [{
        'supplier_part_number': 'DEMO-PAINT-01',
        'unit_price': '95',
        'currency': 'JPY',
        'updated_at': DEMO_DATE,
    }],
}
_DEMO_MAPPING = [{
    'supplier_part_number': 'DEMO-PAINT-01',
    'item_id': 'demo-m13-paint',
    'name': '架空サンプル塗料',
    'category': '塗料',
    'unit': 'ml',
}]


def run(payload: dict, store) -> dict:
    """Stage local fixture offers or save explicitly selected approvals."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'stage')
    if action == 'approve':
        batch_id = text_value(payload.get('import_batch_id'), 'import_batch_id')
        batch = store.latest('import_batch', batch_id)
        candidate_ids = payload.get('candidate_ids')
        if (not isinstance(candidate_ids, list) or not candidate_ids or
                any(candidate_id not in batch['candidate_ids'] for candidate_id in candidate_ids)):
            raise ValidationError('candidate_ids: この卸fixtureの候補から選択してください')
        result = approve_rows(store, candidate_ids, approved_by(payload))
        result.update(import_batch_id=batch_id, simulator=True, api_connected=False)
        return result

    if action not in ('sample', 'stage'):
        raise ValidationError('action: sample / stage / approve を指定してください')
    if action == 'sample':
        feed, mapping = _DEMO_FEED, _DEMO_MAPPING
    else:
        feed, mapping = payload.get('feed'), payload.get('part_number_mapping')

    source, schema_version, offers = _validate_feed(feed)
    mapping_by_part = _validate_mapping(mapping)
    offer_parts = [offer['supplier_part_number'] for offer in offers]
    if len(offer_parts) != len(set(offer_parts)):
        raise ValidationError('offers: 仕入先品番の重複を解消してください')
    if any(part_number not in mapping_by_part for part_number in offer_parts):
        raise ValidationError('part_number_mapping: 全仕入先品番の対応づけが必要です')

    rows = []
    for offer in offers:
        part_number = offer['supplier_part_number']
        mapped = mapping_by_part[part_number]
        rows.append({
            'item_id': mapped['item_id'],
            'name': mapped['name'],
            'category': mapped['category'],
            'unit': mapped['unit'],
            'unit_price': offer['unit_price'],
            'price_type': '仕入',
            'source': f'simulator:未接続fixture:{source}:schema-{schema_version}:part-{part_number}',
            'updated_at': offer['updated_at'],
        })

    with store.transaction():
        staged = stage_rows(store, rows, source)
        batch = store.put('import_batch', {
            'source': source,
            'schema_version': schema_version,
            'terms_status': 'approved',
            'candidate_ids': [row['record_id'] for row in staged['staged_rows']],
            'imported_at': datetime.now(timezone.utc).isoformat(),
            'simulator': True,
            'api_connected': False,
            'mode': 'fixture',
        })
    return {
        'status': '人の確認待ち',
        'import_batch_id': batch['record_id'],
        'staged_rows': staged['staged_rows'],
        'items': [],
        'simulator': True,
        'api_connected': False,
        'source': source,
        'schema_version': schema_version,
    }


def _validate_feed(feed):
    if not isinstance(feed, dict):
        raise ValidationError('feed: 卸提供JSON fixtureが必要です')
    mode = text_value(feed.get('mode'), 'mode')
    if mode != 'fixture':
        raise ValidationError('mode: live接続は未許諾・未実装のため利用できません')
    source = text_value(feed.get('source'), 'source')
    if len(source) > 120 or any(ord(char) < 32 for char in source):
        raise ValidationError('source: 120文字以下で指定してください')
    if feed.get('terms_status') != 'approved':
        raise ValidationError('terms_status: 利用許諾の確認が必要です')
    schema_version = text_value(feed.get('schema_version'), 'schema_version')
    if schema_version != '1':
        raise ValidationError('schema_version: 対応するfixture schemaは1です')
    offers = feed.get('offers')
    if not isinstance(offers, list) or not offers or len(offers) > 1000:
        raise ValidationError('offers: 1〜1000件の候補が必要です')
    normalized = []
    for index, offer in enumerate(offers, 1):
        if not isinstance(offer, dict):
            raise ValidationError(f'offers[{index}]: fixtureの行を確認してください')
        part_number = text_value(offer.get('supplier_part_number'), f'offers[{index}].supplier_part_number')
        if len(part_number) > 128 or any(ord(char) < 32 for char in part_number):
            raise ValidationError(f'offers[{index}].supplier_part_number: 128文字以下で指定してください')
        unit_price = text_value(offer.get('unit_price'), f'offers[{index}].unit_price')
        # Use shared Decimal validation while retaining its exact decimal string.
        unit_price = str(decimal_value(unit_price, f'offers[{index}].unit_price', positive=True))
        if offer.get('currency') != 'JPY':
            raise ValidationError(f'offers[{index}].currency: JPY以外は自動換算できません')
        updated_at = text_value(offer.get('updated_at'), f'offers[{index}].updated_at')
        updated_at = date_value(updated_at, f'offers[{index}].updated_at').isoformat()
        normalized.append({'supplier_part_number': part_number, 'unit_price': unit_price,
                           'updated_at': updated_at})
    return source, schema_version, normalized


def _validate_mapping(mapping):
    if not isinstance(mapping, list) or not mapping or len(mapping) > 1000:
        raise ValidationError('part_number_mapping: 品番対応づけが必要です')
    mapping_by_part = {}
    for index, entry in enumerate(mapping, 1):
        if not isinstance(entry, dict):
            raise ValidationError(f'part_number_mapping[{index}]: 対応づけを確認してください')
        part_number = text_value(entry.get('supplier_part_number'), f'part_number_mapping[{index}].supplier_part_number')
        if part_number in mapping_by_part:
            raise ValidationError('part_number_mapping: 仕入先品番の重複を解消してください')
        local_item = {
            'item_id': text_value(entry.get('item_id'), f'part_number_mapping[{index}].item_id'),
            'name': text_value(entry.get('name'), f'part_number_mapping[{index}].name'),
            'category': text_value(entry.get('category'), f'part_number_mapping[{index}].category'),
            'unit': text_value(entry.get('unit'), f'part_number_mapping[{index}].unit'),
        }
        if local_item['category'] not in ('部品', '塗料', '溶剤', '消耗品'):
            raise ValidationError(f'part_number_mapping[{index}].category: 選択値を確認してください')
        mapping_by_part[part_number] = local_item
    return mapping_by_part
