"""M21: calculate paint formula quantities proportionally."""

from decimal import Decimal, localcontext
from uuid import uuid4

from .core import DEMO_DATE, ValidationError, approved_by, date_value, decimal_value, text_value


SPEC = {
    'idea_id': 'M21',
    'title': '配合量の比例計算',
    'description': 'M05の承認済み配合版と確認済み価格を使い、必要量を計算してスナップショット保存します。',
    'defaults': {
        'action': 'register_formula',
        'formula_id': 'demo-m21-blue',
        'code': 'SIM-M21-BLUE',
        'version': 1,
        'status': 'approved',
        'confirmed_by': '架空デモ担当',
        'formula_lines': [
            {'item_id': 'demo-paint', 'ratio': '1', 'unit': 'ml'},
        ],
    },
}

FORMULA_NAMESPACE = 'formula'
SNAPSHOT_NAMESPACE = 'formula_quantity_snapshot'
APPROVAL_NAMESPACE = 'formula_quantity_approval'


def run(payload: dict, store) -> dict:
    """Register a M05-compatible formula, calculate, or approve a snapshot."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'calculate')
    if action == 'register_formula':
        return _register_formula(payload, store)
    if action == 'calculate':
        return _calculate(payload, store)
    if action == 'approve_snapshot':
        return _approve_snapshot(payload, store)
    if action == 'get_snapshot':
        snapshot_id = text_value(payload.get('snapshot_id'), 'snapshot_id')
        return {'snapshot': store.latest(SNAPSHOT_NAMESPACE, snapshot_id), 'simulator': True}
    raise ValidationError('action: register_formula / calculate / approve_snapshot / get_snapshot を選択してください')


def _register_formula(payload, store):
    formula_id = text_value(payload.get('formula_id'), 'formula_id')
    code = text_value(payload.get('code'), 'code')
    version = payload.get('version')
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValidationError('version: 1以上の整数が必要です')
    status = payload.get('status', 'pending')
    if status not in ('approved', 'pending'):
        raise ValidationError('status: approved または pending を指定してください')
    confirmer = approved_by(payload)
    raw_lines = payload.get('formula_lines')
    if not isinstance(raw_lines, list) or not raw_lines or len(raw_lines) > 100:
        raise ValidationError('formula_lines: 1〜100件の構成が必要です')

    lines = []
    seen_items = set()
    ratio_total = Decimal('0')
    with localcontext() as context:
        context.prec = 80
        for index, line in enumerate(raw_lines):
            if not isinstance(line, dict):
                raise ValidationError(f'formula_lines[{index}]: 構成を確認してください')
            item_id = text_value(line.get('item_id'), f'formula_lines[{index}].item_id')
            if item_id in seen_items:
                raise ValidationError('formula_lines: 同じ品目は1行にまとめてください')
            seen_items.add(item_id)
            ratio = decimal_value(line.get('ratio'), f'formula_lines[{index}].ratio', positive=True)
            if ratio > 1:
                raise ValidationError(f'formula_lines[{index}].ratio: 1以下で入力してください')
            unit = text_value(line.get('unit'), f'formula_lines[{index}].unit')
            lines.append({'item_id': item_id, 'ratio': str(ratio), 'unit': unit})
            ratio_total += ratio
    if ratio_total != Decimal('1'):
        raise ValidationError('配合比率不整合: 比率の合計を1にしてください')

    formula = {
        'formula_id': formula_id, 'code': code, 'version': version,
        'status': status, 'confirmed_by': confirmer,
        'formula_lines': lines, 'source': 'simulator:架空レシピ',
    }
    with store.transaction():
        store.put(FORMULA_NAMESPACE, formula, record_id=formula_id)
    return {'formula': formula, 'simulator': True}


def _get_formula(payload, store):
    formula_id = text_value(payload.get('formula_id'), 'formula_id')
    version = payload.get('version')
    rows = store.records(FORMULA_NAMESPACE, formula_id)
    if version is not None:
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValidationError('version: 1以上の整数が必要です')
        rows = [row for row in rows if row.get('version') == version]
    if not rows:
        raise ValidationError('formula: 指定した配合版がありません')
    formula = rows[-1]
    if formula.get('status') != 'approved' or not formula.get('confirmed_by'):
        raise ValidationError('未承認配合: 担当者の承認が必要です')
    lines = formula.get('formula_lines')
    if not isinstance(lines, list) or not lines:
        raise ValidationError('配合構成不整合: 構成を確認してください')
    ratio_total = Decimal('0')
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            raise ValidationError('配合構成不整合: 構成を確認してください')
        text_value(line.get('item_id'), f'formula_lines[{index}].item_id')
        text_value(line.get('unit'), f'formula_lines[{index}].unit')
        ratio_total += decimal_value(line.get('ratio'), f'formula_lines[{index}].ratio', positive=True)
    if ratio_total != Decimal('1'):
        raise ValidationError('配合比率不整合: 比率の合計を1にしてください')
    return formula


def _calculate(payload, store):
    formula = _get_formula(payload, store)
    total_qty = decimal_value(payload.get('total_qty'), 'total_qty', positive=True)
    unit = text_value(payload.get('unit'), 'unit')
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    calculated_lines = []
    total_cost = Decimal('0')
    simulator = str(formula.get('source', '')).startswith('simulator:')
    with localcontext() as context:
        context.prec = 80
        for line in formula['formula_lines']:
            if line.get('unit') != unit:
                raise ValidationError('単位不一致: 配合構成と必要総量の単位が一致しません')
            ratio = decimal_value(line.get('ratio'), 'ratio', positive=True)
            quantity = total_qty * ratio
            price = store.get_price(line['item_id'], '仕入', as_of=as_of, unit=unit)
            item = price['item']
            simulator = simulator or item['source'].startswith('simulator:')
            if item['category'] not in ('塗料', '溶剤'):
                raise ValidationError('配合構成品は塗料または溶剤を指定してください')
            unit_price = decimal_value(item['unit_price'], 'unit_price')
            if unit_price == 0:
                raise ValidationError('価格未確認: 0円の価格では計算できません')
            line_cost = quantity * unit_price
            total_cost += line_cost
            calculated_lines.append({
                'item_id': item['item_id'], 'name': item['name'],
                'ratio': str(ratio), 'quantity': str(quantity), 'unit': unit,
                'unit_price': str(unit_price), 'price_type': item['price_type'],
                'price_version_id': price['price_version_id'],
                'line_cost': str(line_cost),
            })

    snapshot_id = uuid4().hex
    snapshot = {
        'snapshot_id': snapshot_id,
        'formula_id': formula['formula_id'], 'formula_code': formula['code'],
        'formula_version': formula['version'],
        'formula_confirmed_by': formula['confirmed_by'],
        'formula_source': formula['source'],
        'total_qty': str(total_qty), 'unit': unit, 'as_of': as_of,
        'lines': calculated_lines, 'total_cost': str(total_cost), 'currency': 'JPY',
        'status': 'needs_human_confirmation', 'confirmed_by': None,
        'simulator': simulator,
    }
    store.put(SNAPSHOT_NAMESPACE, snapshot, record_id=snapshot_id)
    return {'snapshot': snapshot, 'simulator': snapshot['simulator'],
            'notice': '数量・価格の計算候補です。承認されるまで見積確定には使用できません。'}


def _approve_snapshot(payload, store):
    snapshot_id = text_value(payload.get('snapshot_id'), 'snapshot_id')
    confirmer = approved_by(payload)
    snapshot = store.latest(SNAPSHOT_NAMESPACE, snapshot_id)
    if snapshot.get('status') != 'needs_human_confirmation':
        raise ValidationError('snapshot: 承認待ちの計算結果ではありません')
    approval = {
        'snapshot_id': snapshot_id, 'confirmed_by': confirmer,
        'status': 'approved', 'formula_id': snapshot['formula_id'],
        'formula_version': snapshot['formula_version'],
    }
    with store.transaction():
        store.put(APPROVAL_NAMESPACE, approval, record_id=snapshot_id)
        approved_snapshot = dict(snapshot, status='approved', confirmed_by=confirmer)
        store.put(SNAPSHOT_NAMESPACE, approved_snapshot, record_id=snapshot_id)
    return {'snapshot': approved_snapshot, 'approval': approval, 'simulator': snapshot['simulator']}
