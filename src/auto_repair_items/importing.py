"""M09–M13 staging/approval helpers: only whitelisted item data persists."""
from .core import ITEM_FIELDS, ValidationError, text_value, validate_item


def stage_rows(store, rows, source, field_map=None):
    """field_map maps canonical target names to source column names.

    Bad rows are quarantined with error messages. Raw full documents, personal
    information and unmapped columns are deliberately not retained.
    """
    source = text_value(source, 'source')
    if not isinstance(rows, list) or not rows or len(rows) > 1000:
        raise ValidationError('rows: 1〜1000行の品目情報が必要です')
    if field_map is not None and (not isinstance(field_map, dict) or
            any(key not in ITEM_FIELDS or not isinstance(value, str) for key, value in field_map.items())):
        raise ValidationError('field_map: 共通品目項目への列対応を確認してください')
    staged_rows = []
    with store.transaction():
        for index, row in enumerate(rows):
            errors = []
            item = None
            if not isinstance(row, dict):
                errors.append('行は品目項目の集合で指定してください')
            else:
                candidate = {key: row.get(field_map.get(key, key) if field_map else key) for key in ITEM_FIELDS}
                if candidate.get('source') is None or candidate.get('source') == '':
                    candidate['source'] = source
                try:
                    item = validate_item(candidate)
                except ValidationError as error:
                    errors.append(str(error))
            staged = store.put('staging_row', {
                'row_number': index + 1, 'item': item, 'source': source,
                'status': 'quarantined' if errors else 'pending', 'errors': errors,
            })
            staged_rows.append(staged)
    return {'staged_rows': staged_rows, 'status': '人の確認待ち', 'items': []}


def approve_rows(store, candidate_ids, confirmed_by):
    confirmed_by = text_value(confirmed_by, 'confirmed_by')
    if not isinstance(candidate_ids, list) or not candidate_ids:
        raise ValidationError('candidate_ids: 候補IDを選択してください')
    candidate_ids = [text_value(candidate_id, 'candidate_id') for candidate_id in candidate_ids]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValidationError('candidate_ids: 重複のない候補IDを選択してください')
    versions = []
    with store.transaction():
        for candidate_id in candidate_ids:
            candidate_id = text_value(candidate_id, 'candidate_id')
            row = store.latest('staging_row', candidate_id)
            if row['status'] != 'pending' or row['item'] is None:
                raise ValidationError('取込不備の行は承認できません')
            if store.records('import_approval', candidate_id):
                raise ValidationError('この候補はすでに承認されています')
            version = store.add_price(row['item'], confirmed_by, reason='取込候補を人が確認')
            store.put('import_approval', {'candidate_id': candidate_id,
                'price_version_id': version['price_version_id'], 'confirmed_by': confirmed_by}, candidate_id)
            versions.append(version)
    return {'items': [version['item'] for version in versions],
            'price_version_ids': [version['price_version_id'] for version in versions], 'status': '承認済み'}
