"""Unified API for the human-confirmed repair-item workflow."""

from decimal import localcontext
from uuid import uuid4

from . import m09, m23, m30
from .core import DEMO_DATE, ValidationError, approved_by, date_value, price_conditions, text_value, validate_item


SPEC = {
    'idea_id': 'INTEGRATED',
    'title': '品目・見積の統合ワークフロー',
    'description': '在庫確認、品目登録、CSV取込、見積保存と実使用記録を一つのAPIで扱います。',
    'defaults': {},
}

IMPORT_BATCH_NAMESPACE = 'integrated_import_batch'


def run(payload: dict, store) -> dict:
    """Dispatch atomically and calculate decimals without implicit rounding."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = text_value(payload.get('action'), 'action')
    with localcontext() as context:
        context.prec = 120
        if action in {'dashboard', 'get_quote'}:
            return _dispatch(payload, store)
        with store.transaction():
            return _dispatch(payload, store)


def _dispatch(payload: dict, store) -> dict:
    """Dispatch one workflow action."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = text_value(payload.get('action'), 'action')
    if action == 'dashboard':
        return _dashboard(payload, store)
    if action in ('register', 'update_price'):
        return _register(payload, store)
    if action == 'stage_csv':
        return _stage_csv(payload, store)
    if action == 'approve_import':
        return _approve_import(payload, store)
    if action == 'save_quote':
        return m30.run({**payload, 'action': 'save'}, store)
    if action == 'get_quote':
        return m30.run({'action': 'get', 'quote_id': payload.get('quote_id')}, store)
    if action == 'record_usage':
        return m23.run({**payload, 'action': 'record'}, store)
    if action == 'tool':
        from .registry import module_for
        idea_id = text_value(payload.get('idea_id'), 'idea_id')
        if idea_id not in {'M02', 'M05', 'M19', 'M20', 'M21', 'M22', 'M24', 'M25', 'M26', 'M27', 'M28', 'M29'}:
            raise ValidationError('idea_id: 委譲可能な案を選択してください')
        tool_payload = payload.get('payload')
        if (not isinstance(tool_payload, dict) or not tool_payload.get('action')
                or str(tool_payload.get('action', '')).endswith('_demo')
                or tool_payload.get('action') in {'save_demo', 'record_demo', 'quote_demo'}):
            raise ValidationError('payload.action: デモ動作ではない入力を指定してください')
        return module_for(idea_id).run(tool_payload, store)
    raise ValidationError('action: dashboard / register / update_price / stage_csv / approve_import / save_quote / get_quote / record_usage')


def _dashboard(payload, store):
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of')
    grouped = {}
    for version in store.price_versions():
        item = version.get('item') or {}
        key = (item.get('item_id'), item.get('price_type'), version.get('supplier_id', ''))
        grouped.setdefault(key, []).append(version)
    current = {}
    for key, history in grouped.items():
        eligible = []
        for version in history:
            start = date_value(version['valid_from'], 'valid_from')
            if version.get('status') == 'approved' and start <= as_of:
                eligible.append(version)
        current[key] = max(eligible, key=lambda version: (version['valid_from'], history.index(version))) if eligible else history[-1]
    inventory = []
    for version in current.values():
        item = version['item']
        start = date_value(version['valid_from'], 'valid_from')
        end = date_value(version['valid_until'], 'valid_until') if version.get('valid_until') else None
        checked_at = version.get('metadata', {}).get('checked_at')
        checked_date = date_value(checked_at, 'checked_at') if checked_at else None
        issues = []
        if checked_date and checked_date > as_of:
            issues.append('確認日が適用日より未来')
        if version.get('status') != 'approved':
            issues.append('未承認')
        if start > as_of or (end and end < as_of):
            issues.append('有効期間外')
        if not issues and checked_date is None:
            issues.append('価格確認日不明')
        inventory.append({**item, 'price_version_id': version['price_version_id'],
                          'supplier_id': version.get('supplier_id', ''),
                          'valid_from': version['valid_from'], 'valid_until': version.get('valid_until'),
                          'age_days': (as_of - checked_date).days if checked_date else None,
                          'freshness': '未確認' if '価格確認日不明' in issues else ('current' if not issues else 'stale'), 'issues': issues,
                          'conditions': price_conditions(version)})
    inventory.sort(key=lambda row: (row['item_id'], row['price_type'], row['supplier_id']))
    return {'status': 'ok', 'as_of': as_of.isoformat(), 'summary': {
                'item_count': len({row['item_id'] for row in inventory}),
                'price_count': len(inventory), 'issue_count': sum(bool(row['issues']) for row in inventory)},
            'inventory': inventory,
            'quotes': store.records(m30.QUOTE_NAMESPACE), 'issues': [
                {'item_id': row['item_id'], 'price_version_id': row['price_version_id'], 'issues': row['issues']}
                for row in inventory if row['issues']], 'simulator': any(str(row.get('source', '')).startswith('simulator:') for row in inventory)}


def _register(payload, store):
    item = validate_item(payload.get('item'))
    confirmer = approved_by(payload)
    reason = text_value(payload.get('reason'), 'reason')
    supplier_id = _supplier_id(payload, store, item['item_id'], item['price_type'])
    previous = store.price_versions(item['item_id'], item['price_type'], supplier_id)
    prior = previous[-1] if previous else None
    valid_from = payload.get('valid_from', item['updated_at'])
    valid_until = payload.get('valid_until', prior.get('valid_until') if prior else None)
    supplied_conditions = payload.get('conditions', {})
    if not isinstance(supplied_conditions, dict):
        raise ValidationError('conditions: 取引条件を確認してください')
    metadata = dict(prior.get('metadata', {})) if prior else {}
    for key, value in supplied_conditions.items():
        if key == 'conditions' and isinstance(value, dict):
            nested = dict(metadata.get('conditions', {}))
            nested.update(value)
            metadata[key] = nested
            for term_key, term_value in value.items():
                metadata[term_key] = term_value
        else:
            metadata[key] = value
            nested = dict(metadata.get('conditions', {}))
            if key in nested:
                nested[key] = value
                metadata['conditions'] = nested
    # Validate the merged flat and nested terms before appending a version.
    price_conditions({'metadata': metadata})
    if payload.get('checked_at'):
        metadata['checked_at'] = date_value(payload['checked_at'], 'checked_at').isoformat()
    # Omitted update terms inherit the previous terms and validity. Explicit null
    # valid_until clears the end date; explicit conditions merge only the supplied terms.
    saved = store.add_price(item, confirmer, supplier_id=supplier_id,
                            valid_from=valid_from, valid_until=valid_until, reason=reason, **metadata)
    return {'status': 'saved', 'item': saved['item'], 'price_version': saved,
            'simulator': str(item['source']).startswith('simulator:')}


def _supplier_id(payload, store, item_id, price_type):
    if 'supplier_id' in payload:
        return text_value(payload['supplier_id'], 'supplier_id') if payload['supplier_id'] else ''
    suppliers = {version.get('supplier_id', '') for version in store.price_versions(item_id, price_type)}
    if len(suppliers) > 1:
        raise ValidationError('supplier_id: 複数の仕入先があるため指定してください')
    return next(iter(suppliers), '')


def _stage_csv(payload, store):
    with store.transaction():
        stage_payload = {'action': 'stage', 'csv_text': payload.get('csv_text'),
                         'source': payload.get('source', 'CSV取込'), 'field_map': payload.get('field_map')}
        if payload.get('source_key') is not None:
            stage_payload['source_key'] = payload['source_key']
        requested_batch_id = payload.get('import_batch_id', payload.get('batch_id'))
        batch_id = text_value(requested_batch_id, 'import_batch_id') if requested_batch_id is not None else uuid4().hex
        if store.records(IMPORT_BATCH_NAMESPACE, batch_id):
            raise ValidationError('import_batch_id: 既存バッチIDです')
        result = m09.run(stage_payload, store)
        candidate_ids = [row['record_id'] for row in result['staged_rows']]
        store.put(IMPORT_BATCH_NAMESPACE, {'batch_id': batch_id, 'candidate_ids': candidate_ids,
                   'source_key': result['source_key'], 'mapping_version': result['mapping_version']}, record_id=batch_id)
    return {**result, 'batch_id': batch_id, 'import_batch_id': batch_id}


def _approve_import(payload, store):
    batch_id = text_value(payload.get('import_batch_id', payload.get('batch_id')), 'import_batch_id')
    batch = store.latest(IMPORT_BATCH_NAMESPACE, batch_id)
    candidate_ids = payload.get('candidate_ids')
    if not isinstance(candidate_ids, list) or not candidate_ids:
        raise ValidationError('candidate_ids: 候補IDを選択してください')
    if any(candidate_id not in batch['candidate_ids'] for candidate_id in candidate_ids):
        raise ValidationError('candidate_ids: 指定バッチに属する候補を選択してください')
    confirmer = approved_by(payload)
    with store.transaction():
        result = m09.run({'action': 'approve', 'candidate_ids': candidate_ids,
                          'confirmed_by': confirmer}, store)
        store.put(IMPORT_BATCH_NAMESPACE, {**batch, 'approved_candidate_ids': sorted(set(
            batch.get('approved_candidate_ids', []) + candidate_ids))}, record_id=batch_id)
    return result
