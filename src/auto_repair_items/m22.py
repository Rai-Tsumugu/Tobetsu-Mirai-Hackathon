"""M22: suggest operation-specific material candidates for human selection."""

from decimal import Decimal
from uuid import uuid4

from .core import DEMO_DATE, ValidationError, approved_by, date_value, decimal_value, text_value


SPEC = {
    'idea_id': 'M22',
    'title': '工程別材料候補',
    'description': '①の工程に対応する材料候補を提示し、人が品目・数量・単位を確定した後だけ④向けsnapshotを作ります。',
    'defaults': {
        'action': 'register_rule', 'operation_id': 'rust-treatment',
        'item_id': 'demo-m22-paint', 'required_when': '架空: 塗装工程を選択した場合',
        'quantity_rule': '架空: 人が数量を入力', 'evidence': 'simulator:架空デモ用の仮定',
        'confirmed_by': '架空デモ担当',
    },
}

RULE_NAMESPACE = 'operation_material'
SUGGESTION_NAMESPACE = 'operation_material_suggestion'
SNAPSHOT_NAMESPACE = 'operation_material_quantity_snapshot'


def run(payload: dict, store) -> dict:
    """Register an explicit mapping, suggest from labor, or confirm a quote line."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'suggest')
    if action == 'register_rule':
        _check_keys(payload, {'action', 'operation_id', 'item_id', 'required_when',
                              'quantity_rule', 'evidence', 'confirmed_by'})
        return _register_rule(payload, store)
    if action == 'suggest':
        _check_keys(payload, {'action', 'labor', 'proposed_rules'})
        return _suggest(payload, store)
    if action == 'confirm_selection':
        _check_keys(payload, {'action', 'suggestion_id', 'operation_id', 'item_id',
                              'quantity', 'unit', 'price_type', 'as_of', 'confirmed_by'})
        return _confirm_selection(payload, store)
    if action == 'get_snapshot':
        _check_keys(payload, {'action', 'snapshot_id'})
        snapshot_id = text_value(payload.get('snapshot_id'), 'snapshot_id')
        return {'snapshot': store.latest(SNAPSHOT_NAMESPACE, snapshot_id)}
    raise ValidationError('action: register_rule / suggest / confirm_selection / get_snapshot を選択してください')


def _check_keys(payload, allowed):
    if set(payload) - allowed:
        raise ValidationError('payload: 指定できない項目があります')


def _register_rule(payload, store):
    operation_id = text_value(payload.get('operation_id'), 'operation_id')
    item_id = text_value(payload.get('item_id'), 'item_id')
    required_when = text_value(payload.get('required_when'), 'required_when')
    quantity_rule = text_value(payload.get('quantity_rule'), 'quantity_rule')
    evidence = text_value(payload.get('evidence'), 'evidence')
    confirmer = approved_by(payload)
    rule = {
        'operation_id': operation_id, 'item_id': item_id,
        'required_when': required_when, 'quantity_rule': quantity_rule,
        'evidence': evidence, 'confirmed_by': confirmer, 'status': 'approved',
    }
    saved = store.put(RULE_NAMESPACE, rule)
    return {'status': 'saved', 'rule_id': saved['record_id'], 'rule': rule,
            'simulator': evidence.startswith('simulator:')}


def _valid_labor(payload):
    labor = payload.get('labor')
    if not isinstance(labor, dict) or not isinstance(labor.get('breakdown'), list):
        raise ValidationError('labor.breakdown: 工程一覧を確認してください')
    if len(labor['breakdown']) > 100:
        raise ValidationError('labor.breakdown: 工程数が多すぎます')
    operations = []
    seen = set()
    for index, row in enumerate(labor['breakdown']):
        if not isinstance(row, dict):
            raise ValidationError(f'labor.breakdown[{index}]: 工程を確認してください')
        operation_id = text_value(row.get('operation'), f'labor.breakdown[{index}].operation')
        status = text_value(row.get('status'), f'labor.breakdown[{index}].status')
        # Preserve input status while only considering confirmed/conditional operations.
        if operation_id not in seen:
            operations.append({'operation_id': operation_id, 'status': status})
            seen.add(operation_id)
    return operations


def _suggest(payload, store):
    operations = _valid_labor(payload)
    proposal_rules = payload.get('proposed_rules', [])
    if not isinstance(proposal_rules, list) or len(proposal_rules) > 100:
        raise ValidationError('proposed_rules: 候補辞書を確認してください')
    # Proposal payloads are visible for this call only; suggesting never writes mappings/items.
    proposed = []
    for index, row in enumerate(proposal_rules):
        if not isinstance(row, dict):
            raise ValidationError(f'proposed_rules[{index}]: 候補を確認してください')
        proposed.append({
            'operation_id': text_value(row.get('operation_id'), f'proposed_rules[{index}].operation_id'),
            'item_id': text_value(row.get('item_id'), f'proposed_rules[{index}].item_id'),
            'required_when': text_value(row.get('required_when'), f'proposed_rules[{index}].required_when'),
            'quantity_rule': text_value(row.get('quantity_rule'), f'proposed_rules[{index}].quantity_rule'),
            'evidence': text_value(row.get('evidence'), f'proposed_rules[{index}].evidence'),
            'confirmed_by': text_value(row.get('confirmed_by'), f'proposed_rules[{index}].confirmed_by'),
            'status': 'proposed',
        })
    candidates = []
    unknowns = []
    for operation in operations:
        operation_id = operation['operation_id']
        if operation['status'] not in ('confirmed', 'conditional'):
            unknowns.append({'operation_id': operation_id,
                             'question': 'この工程の実施有無・状態を人が確認してください。材料候補は追加していません。'})
            continue
        matching = [row for row in store.records(RULE_NAMESPACE)
                    if row.get('operation_id') == operation_id and row.get('status') == 'approved'
                    and row.get('confirmed_by')]
        matching.extend(row for row in proposed if row['operation_id'] == operation_id)
        if not matching:
            unknowns.append({'operation_id': operation_id,
                             'question': 'この工程で使う材料候補と根拠を登録・確認してください。'})
        for row in matching:
            candidates.append({
                'operation_id': operation_id, 'operation_status': operation['status'],
                'item_id': row['item_id'], 'required_when': row['required_when'],
                'quantity_rule': row['quantity_rule'], 'evidence': row['evidence'],
                'mapping_status': row['status'], 'mapping_confirmed_by': row['confirmed_by'],
            })
    suggestion_id = uuid4().hex
    suggestion = {'suggestion_id': suggestion_id, 'candidates': candidates,
                  'unknowns': unknowns, 'labor_operation_count': len(operations)}
    store.put(SUGGESTION_NAMESPACE, suggestion, record_id=suggestion_id)
    return {'suggestion': suggestion, 'simulator': any(row['evidence'].startswith('simulator:') for row in candidates)}


def _confirm_selection(payload, store):
    suggestion_id = text_value(payload.get('suggestion_id'), 'suggestion_id')
    operation_id = text_value(payload.get('operation_id'), 'operation_id')
    item_id = text_value(payload.get('item_id'), 'item_id')
    quantity = decimal_value(payload.get('quantity'), 'quantity', positive=True)
    unit = text_value(payload.get('unit'), 'unit')
    price_type = payload.get('price_type', '販売')
    confirmer = approved_by(payload)
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    suggestion = store.latest(SUGGESTION_NAMESPACE, suggestion_id)
    matches = [row for row in suggestion['candidates']
               if row['operation_id'] == operation_id and row['item_id'] == item_id]
    if not matches:
        raise ValidationError('候補未確認: 提示された工程・品目から選択してください')
    candidate = matches[-1]
    version = store.get_price(item_id, price_type, as_of=as_of, unit=unit)
    item = dict(version['item'])
    # Snapshot binds the human-entered quantity to the exact approved item/price version.
    snapshot_id = uuid4().hex
    amount = quantity * Decimal(item['unit_price'])
    snapshot = {
        'snapshot_id': snapshot_id, 'idea_id': 'M22',
        'operation_id': operation_id, 'operation_status': candidate['operation_status'],
        'item': item, 'quantity': str(quantity), 'unit': unit,
        'price_version_id': version['price_version_id'],
        'candidate_rule': candidate, 'confirmed_by': confirmer,
        'as_of': as_of, 'candidate_amount': str(amount), 'currency': 'JPY',
        'status': 'confirmed_for_quote_review',
        'labor_cost_included': False,
    }
    store.put(SNAPSHOT_NAMESPACE, snapshot, record_id=snapshot_id)
    return {'status': snapshot['status'], 'snapshot_id': snapshot_id,
            'material_snapshot': snapshot,
            'items': [item], 'quantity_snapshot_ref': snapshot_id,
            'simulator': item['source'].startswith('simulator:') or candidate['evidence'].startswith('simulator:')}
