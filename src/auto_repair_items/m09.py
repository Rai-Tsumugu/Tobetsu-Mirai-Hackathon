"""M09: map CSV columns, inspect staged rows, and approve selected candidates."""

import csv
from io import StringIO

from .core import DEMO_DATE, ITEM_FIELDS, ValidationError, text_value
from .importing import approve_rows, stage_rows


_DEMO_HEADERS = (
    '商品コード', '品名', '分類', '単位', '単価', '価格区分', '出所', '確認日',
)
_DEMO_CSV = '\n'.join((
    ','.join(_DEMO_HEADERS),
    'demo-m09-paint,架空デモ塗料,塗料,ml,95,仕入,simulator:架空値,' + DEMO_DATE,
    'demo-m09-thinner,架空デモ溶剤,溶剤,L,480,仕入,simulator:架空値,' + DEMO_DATE,
))
_DEMO_FIELD_MAP = dict(zip(ITEM_FIELDS, _DEMO_HEADERS))

SPEC = {
    'idea_id': 'M09',
    'title': 'CSV列対応ウィザード',
    'description': 'CSV列を共通品目項目へ対応づけ、行ごとの検品後に選択候補だけを人が承認します。',
    'defaults': {
        'action': 'stage',
        'csv_text': _DEMO_CSV,
        'source': 'simulator:架空値',
        'source_key': 'demo-m09-csv',
        'field_map': _DEMO_FIELD_MAP,
    },
}


def run(payload: dict, store) -> dict:
    """Stage a CSV preview or approve explicitly selected staged row IDs."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'stage')
    if action == 'stage':
        return _stage(payload, store)
    if action == 'approve':
        return _approve(payload, store)
    raise ValidationError('action: stage または approve を指定してください')


def _stage(payload: dict, store) -> dict:
    csv_text = payload.get('csv_text')
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValidationError('csv_text: CSV本文が必要です')
    if len(csv_text.encode('utf-8')) > 1_000_000:
        raise ValidationError('csv_text: CSVは1MB以下にしてください')
    source = text_value(payload.get('source', 'simulator:架空値'), 'source')
    source_key = text_value(payload.get('source_key', source), 'source_key')
    if len(source_key) > 128:
        raise ValidationError('source_key: 128文字以下にしてください')

    try:
        reader = csv.DictReader(
            StringIO(csv_text, newline=''),
            restkey='__extra_columns__',
            restval=None,
            strict=True,
        )
        headers = reader.fieldnames
        if not headers:
            raise ValidationError('csv_text: ヘッダー行が必要です')
        if any(not isinstance(header, str) or not header.strip() for header in headers):
            raise ValidationError('csv_text: 空の列名は使用できません')
        if len(headers) != len(set(headers)):
            raise ValidationError('csv_text: 重複した列名があります')
        if '__extra_columns__' in headers:
            raise ValidationError('csv_text: 予約済み列名が含まれています')
        field_map = _validate_field_map(payload.get('field_map'), headers)
        raw_rows = list(reader)
    except csv.Error as error:
        raise ValidationError(f'csv_text: CSV形式を確認してください ({error})') from None

    if not raw_rows or len(raw_rows) > 1000:
        raise ValidationError('csv_text: 1〜1000件の明細が必要です')

    # Drop all unmapped columns before staging so unrelated CSV values never persist.
    mapped_rows = []
    for raw_row in raw_rows:
        row = dict(raw_row)
        # DictReader places excess cells under restkey. Quarantine that row via a
        # required field failure while discarding the extra cell contents.
        if '__extra_columns__' in raw_row:
            row[field_map.get('item_id', 'item_id')] = None
        mapped_rows.append(row)

    existing_versions = store.records('import_mapping', source_key)
    mapping_version = (existing_versions[-1]['version'] + 1) if existing_versions else 1
    with store.transaction():
        staged = stage_rows(store, mapped_rows, source, field_map)
        mapping = store.put('import_mapping', {
            'source_key': source_key,
            'field_map': field_map,
            'version': mapping_version,
        }, record_id=source_key)

    return {
        'status': staged['status'],
        'source_key': source_key,
        'mapping_version': mapping_version,
        'mapping_record_id': mapping['record_id'],
        'field_map': field_map,
        'staged_rows': staged['staged_rows'],
        'preview_count': len(staged['staged_rows']),
        'quarantined_count': sum(row['status'] == 'quarantined' for row in staged['staged_rows']),
        'items': [],
    }


def _validate_field_map(field_map, headers):
    if field_map is None:
        field_map = {field: field for field in ITEM_FIELDS if field in headers}
    if not isinstance(field_map, dict) or any(target not in ITEM_FIELDS for target in field_map):
        raise ValidationError('field_map: 共通品目項目への列対応を確認してください')
    normalized = {}
    for target, column in field_map.items():
        column = text_value(column, f'field_map.{target}')
        if column not in headers:
            raise ValidationError(f'field_map.{target}: CSVに存在する列を選択してください')
        normalized[target] = column

    # Canonical names may be used without an explicit mapping. Every item field
    # must resolve to exactly one source column before any rows are persisted.
    resolved = {field: normalized.get(field, field) for field in ITEM_FIELDS}
    missing = [column for column in resolved.values() if column not in headers]
    if missing:
        raise ValidationError('field_map: 品目ID・品名・分類・単位・単価・価格区分・出所・確認日の列対応が必要です')
    if len(set(resolved.values())) != len(ITEM_FIELDS):
        raise ValidationError('field_map: 同じCSV列を複数の項目に割り当てられません')
    # Persist only explicit, non-identity choices. The canonical fallback is
    # deterministic and needs no separate mapping entry.
    return normalized


def _approve(payload, store):
    mapping_version = payload.get('mapping_version')
    if mapping_version is not None:
        if isinstance(mapping_version, bool) or not isinstance(mapping_version, int) or mapping_version < 1:
            raise ValidationError('mapping_version: 正の版番号が必要です')
        source_key = text_value(payload.get('source_key'), 'source_key')
        mappings = store.records('import_mapping', source_key)
        if not mappings or mappings[-1]['version'] != mapping_version:
            raise ValidationError('mapping_version: 現在の列対応版を確認してください')
    result = approve_rows(store, payload.get('candidate_ids'), payload.get('confirmed_by'))
    result['mapping_version'] = mapping_version
    return result
