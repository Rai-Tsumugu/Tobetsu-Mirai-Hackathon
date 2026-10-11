"""Store and price fictional, human-approved paint formulae."""

from decimal import Decimal, localcontext

from .core import (
    DEMO_DATE,
    ValidationError,
    approved_by,
    date_value,
    decimal_value,
    text_value,
)


SPEC = {
    'idea_id': 'M05',
    'title': '塗料配合構成マスタ',
    'description': '配合を版管理し、承認済み構成品の単位と仕入単価から基準量の金額候補を計算します。',
    'defaults': {
        'action': 'save_formula',
        'formula_id': 'demo-metallic-blue',
        'code': 'SIM-BLUE-01',
        'version': 1,
        'status': 'approved',
        'confirmed_by': '架空デモ担当',
        'formula_lines': [{'item_id': 'demo-paint', 'ratio': '1', 'unit': 'ml'}],
        'base_qty': '100',
        'unit': 'ml',
        'as_of': DEMO_DATE,
    },
}


def run(payload: dict, store) -> dict:
    """Save, retrieve, approve, or calculate a formula.

    Ratios are fractions of the stated base quantity and must sum exactly to
    one. The cost result is a proposal based on approved purchase-price snapshots;
    it is not a paint-use instruction or a real-world coating estimate.
    """
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')

    action = payload.get('action', 'calculate')
    if action == 'save_formula':
        formula = _build_formula(payload)
        with store.transaction():
            store.put('formula', formula, record_id=formula['formula_id'])
            if formula['status'] != 'approved':
                return {'formula': formula, 'simulator': True}
            return _calculate(formula, payload, store)
    if action in ('get_formula', 'calculate'):
        formula = _get_formula(payload, store)
        if action == 'get_formula':
            _require_approved(formula)
            return {'formula': formula, 'simulator': True}
        return _calculate(formula, payload, store)
    if action == 'approve_formula':
        formula_id = text_value(payload.get('formula_id'), 'formula_id')
        current = store.latest('formula', formula_id)
        confirmer = approved_by(payload)
        if current['status'] == 'approved':
            raise ValidationError('配合はすでに承認済みです')
        approved = dict(current)
        approved['status'] = 'approved'
        approved['confirmed_by'] = confirmer
        store.put('formula', approved, record_id=formula_id)
        return {'formula': approved, 'simulator': True}
    raise ValidationError('action: save_formula / get_formula / calculate / approve_formula を選択してください')


def _build_formula(payload: dict) -> dict:
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
    for index, raw_line in enumerate(raw_lines):
        if not isinstance(raw_line, dict):
            raise ValidationError(f'formula_lines[{index}]: 構成を確認してください')
        item_id = text_value(raw_line.get('item_id'), f'formula_lines[{index}].item_id')
        if item_id in seen_items:
            raise ValidationError('formula_lines: 同じ品目は1行にまとめてください')
        seen_items.add(item_id)
        ratio = decimal_value(raw_line.get('ratio'), f'formula_lines[{index}].ratio', positive=True)
        if ratio > 1:
            raise ValidationError(f'formula_lines[{index}].ratio: 1以下で入力してください')
        unit = text_value(raw_line.get('unit'), f'formula_lines[{index}].unit')
        lines.append({'item_id': item_id, 'ratio': str(ratio), 'unit': unit})
        ratio_total += ratio
    if ratio_total != Decimal('1'):
        raise ValidationError('配合比率不整合: 比率の合計を1にしてください')

    return {
        'formula_id': formula_id,
        'code': code,
        'version': version,
        'status': status,
        'confirmed_by': confirmer,
        'formula_lines': lines,
        'source': 'simulator:架空レシピ',
    }


def _get_formula(payload: dict, store) -> dict:
    formula_id = text_value(payload.get('formula_id'), 'formula_id')
    if payload.get('version') is None:
        return store.latest('formula', formula_id)
    version = payload['version']
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValidationError('version: 1以上の整数が必要です')
    matches = [record for record in store.records('formula', formula_id)
               if record.get('version') == version]
    if not matches:
        raise ValidationError('formula: 指定した版がありません')
    return matches[-1]


def _require_approved(formula: dict) -> None:
    if formula.get('status') != 'approved':
        raise ValidationError('未承認配合: 担当者の承認が必要です')


def _calculate(formula: dict, payload: dict, store) -> dict:
    _require_approved(formula)
    unit = text_value(payload.get('unit'), 'unit')
    base_qty = decimal_value(payload.get('base_qty'), 'base_qty', positive=True)
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()

    calculated_lines = []
    total = Decimal('0')
    # Ratios and quantities can each carry up to 28 digits under the shared
    # contract; retain their exact product and sum without context rounding.
    with localcontext() as context:
        context.prec = 80
        for formula_line in formula['formula_lines']:
            if formula_line['unit'] != unit:
                raise ValidationError('単位不一致: 配合構成と基準量の単位が一致しません')
            ratio = decimal_value(formula_line['ratio'], 'ratio', positive=True)
            quantity = ratio * base_qty
            price_version = store.get_price(
                formula_line['item_id'], '仕入', as_of=as_of, unit=formula_line['unit'])
            item = price_version['item']
            if item['category'] not in ('塗料', '溶剤'):
                raise ValidationError('配合構成品は塗料または溶剤を指定してください')
            line_total = decimal_value(item['unit_price'], 'unit_price') * quantity
            total += line_total
            calculated_lines.append({
                'item_id': item['item_id'],
                'name': item['name'],
                'ratio': str(ratio),
                'quantity': str(quantity),
                'unit': item['unit'],
                'unit_price': str(decimal_value(item['unit_price'], 'unit_price')),
                'price_version_id': price_version['price_version_id'],
                'line_total': str(line_total),
            })

    return {
        'formula': formula,
        'base_qty': str(base_qty),
        'unit': unit,
        'as_of': as_of,
        'lines': calculated_lines,
        'total_cost': str(total),
        'currency': 'JPY',
        'confirmed_by': formula['confirmed_by'],
        'simulator': True,
        'notice': '架空価格による金額候補です。塗着率・廃棄分を含まず、実塗装には使用できません。',
    }
