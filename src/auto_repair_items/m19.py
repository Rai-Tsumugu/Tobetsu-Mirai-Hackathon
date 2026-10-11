"""M19: suggest human-reviewed materials by panel and finish."""

from .core import ValidationError, approved_by, text_value


SPEC = {
    'idea_id': 'M19',
    'title': 'パネル・部位材料辞書',
    'description': '部位と仕上げから材料候補を表示し、人が適合を確認して選択します。',
    'defaults': {
        'action': 'list', 'panel_id': 'front_door', 'finish_type': 'metallic',
    },
}

NAMESPACE = 'panel_material'
SELECTION_NAMESPACE = 'panel_material_selection'


def run(payload: dict, store) -> dict:
    """Record dictionary entries, list suggestions, or record a human selection."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'list')
    if action == 'record':
        _check_keys(payload, {'action', 'panel_id', 'finish_type', 'item_id',
                              'applicability', 'source', 'confirmed_by'})
        return _record(payload, store)
    if action == 'list':
        _check_keys(payload, {'action', 'panel_id', 'finish_type'})
        return _list(payload, store)
    if action == 'select':
        _check_keys(payload, {'action', 'panel_id', 'finish_type', 'item_id',
                              'application_condition', 'confirmed_by'})
        return _select(payload, store)
    raise ValidationError('action: record / list / select を選択してください')


def _check_keys(payload, allowed):
    if set(payload) - allowed:
        raise ValidationError('payload: 指定できない項目があります')


def _key(payload):
    return (text_value(payload.get('panel_id'), 'panel_id'),
            text_value(payload.get('finish_type'), 'finish_type'))


def _record(payload, store):
    panel_id, finish_type = _key(payload)
    item_id = text_value(payload.get('item_id'), 'item_id')
    applicability = text_value(payload.get('applicability'), 'applicability')
    source = text_value(payload.get('source'), 'source')
    confirmer = approved_by(payload)
    record = {
        'panel_id': panel_id, 'finish_type': finish_type, 'item_id': item_id,
        'applicability': applicability, 'source': source,
        'confirmed_by': confirmer, 'simulator': source.startswith('simulator:'),
    }
    saved = store.put(NAMESPACE, record)
    return {'status': 'saved', 'panel_material_id': saved['record_id'],
            'candidate': record}


def _list(payload, store):
    panel_id, finish_type = _key(payload)
    rows = [row for row in store.records(NAMESPACE)
            if row['panel_id'] == panel_id and row['finish_type'] == finish_type]
    if not rows and (panel_id, finish_type) == ('front_door', 'metallic'):
        _record({
            'panel_id': panel_id, 'finish_type': finish_type,
            'item_id': 'demo-metallic-paint',
            'applicability': '架空デモ用。実車・工程への適合は未確認',
            'source': 'simulator:架空材料辞書', 'confirmed_by': '架空デモ担当',
        }, store)
        rows = [row for row in store.records(NAMESPACE)
                if row['panel_id'] == panel_id and row['finish_type'] == finish_type]
    candidates = [{key: row[key] for key in (
        'item_id', 'applicability', 'source', 'confirmed_by', 'simulator')}
        for row in rows]
    result = {'panel_id': panel_id, 'finish_type': finish_type,
              'candidates': candidates,
              'simulator': any(row['simulator'] for row in rows)}
    if not candidates:
        result['unknowns'] = ['panel_id/finish_type の材料候補辞書が未登録']
    return result


def _select(payload, store):
    panel_id, finish_type = _key(payload)
    item_id = text_value(payload.get('item_id'), 'item_id')
    condition = text_value(payload.get('application_condition'), 'application_condition')
    confirmer = approved_by(payload)
    candidates = [row for row in store.records(NAMESPACE)
                  if row['panel_id'] == panel_id and row['finish_type'] == finish_type
                  and row['item_id'] == item_id]
    if not candidates:
        raise ValidationError('候補未登録: 選択前に辞書を確認してください')
    candidate = candidates[-1]
    selection = {
        'panel_id': panel_id, 'finish_type': finish_type, 'item_id': item_id,
        'application_condition': condition, 'source': candidate['source'],
        'confirmed_by': confirmer,
    }
    saved = store.put(SELECTION_NAMESPACE, selection)
    return {'status': 'selected', 'selection_id': saved['record_id'],
            'selection': selection, 'simulator': bool(candidate['simulator'])}
