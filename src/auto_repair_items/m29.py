"""M29: explicitly approved rounding rules for quote calculations."""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP
from uuid import uuid4

from .core import ValidationError, approved_by, decimal_value, text_value


SPEC = {
    'idea_id': 'M29',
    'title': '端数処理規約',
    'description': '承認済みの丸め規則を版保存し、見積行と税区分ごとの合計に適用します。',
    'defaults': {
        'action': 'quote_demo',
        'quote_id': 'demo-m29-quote',
        'line_rule_id': 'demo-m29-line-rule',
        'tax_rule_id': 'demo-m29-tax-rule',
        'confirmed_by': '架空デモ担当',
        'tax_rates': {'demo-tax': '0.1'},
        'lines': [
            {'quote_line_id': 'demo-m29-line-1', 'name': '架空デモ材料A', 'quantity': '1',
             'unit_price': '1.005', 'tax_category': 'demo-tax'},
            {'quote_line_id': 'demo-m29-line-2', 'name': '架空デモ材料B', 'quantity': '1',
             'unit_price': '1.005', 'tax_category': 'demo-tax'},
        ],
    },
}

RULE_NAMESPACE = 'rounding_rule'
QUOTE_NAMESPACE = 'quote_snapshot'
_ROUNDING_MODES = {
    'half_up': ROUND_HALF_UP,
    'down': ROUND_DOWN,
    'up': ROUND_CEILING,
    'floor': ROUND_FLOOR,
}
_STAGES = ('line', 'tax_category_total')


def run(payload: dict, store) -> dict:
    """Save an approved rule or calculate a quote with explicitly selected rules."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'quote')
    if action == 'save_rule':
        return _save_rule(payload, store)
    if action == 'quote_demo':
        _seed_demo_rules(store)
        return _quote(payload, store, simulator=True)
    if action == 'quote':
        return _quote(payload, store, simulator=False)
    raise ValidationError('action: save_rule / quote / quote_demo を選択してください')


def _rule_fields(payload):
    rule_id = text_value(payload.get('id'), 'id')
    stage = text_value(payload.get('stage'), 'stage')
    mode = text_value(payload.get('mode'), 'mode')
    if stage not in _STAGES:
        raise ValidationError('stage: line / tax_category_total を選択してください')
    if mode not in _ROUNDING_MODES:
        raise ValidationError('mode: half_up / down / up / floor を選択してください')
    places_value = payload.get('decimal_places')
    if isinstance(places_value, bool) or not isinstance(places_value, int) or not 0 <= places_value <= 6:
        raise ValidationError('decimal_places: 0〜6の整数を指定してください')
    return rule_id, stage, mode, places_value


def _save_rule(payload, store):
    rule_id, stage, mode, decimal_places = _rule_fields(payload)
    confirmer = approved_by(payload)
    version = {
        'id': rule_id, 'stage': stage, 'mode': mode,
        'decimal_places': decimal_places, 'confirmed_by': confirmer,
        'rounding_rule_version_id': uuid4().hex,
    }
    saved = store.put(RULE_NAMESPACE, version, record_id=rule_id)
    return {'status': 'saved', 'rounding_rule': saved, 'simulator': False}


def _seed_demo_rules(store):
    """Seed fictional rules only after an explicit quote_demo action."""
    demo_rules = (
        ('demo-m29-line-rule', 'line'),
        ('demo-m29-tax-rule', 'tax_category_total'),
    )
    for rule_id, stage in demo_rules:
        if not store.records(RULE_NAMESPACE, rule_id):
            _save_rule({'id': rule_id, 'stage': stage, 'mode': 'half_up',
                        'decimal_places': 2, 'confirmed_by': '架空デモ担当'}, store)


def _load_rule(store, rule_id, expected_stage):
    rule_id = text_value(rule_id, f'{expected_stage}_rule_id')
    rule = store.latest(RULE_NAMESPACE, rule_id)
    # Validate saved data again so malformed records cannot influence a quote.
    _, stage, mode, decimal_places = _rule_fields({**rule, 'id': rule_id})
    if stage != expected_stage:
        raise ValidationError(f'{rule_id}: 対象stageが一致しません')
    confirmer = text_value(rule.get('confirmed_by'), 'rounding_rule.confirmed_by')
    version_id = text_value(rule.get('rounding_rule_version_id'), 'rounding_rule.version_id')
    return {
        'id': rule_id, 'rounding_rule_version_id': version_id, 'stage': stage,
        'mode': mode, 'decimal_places': decimal_places, 'confirmed_by': confirmer,
    }


def _round(value, rule):
    quantum = Decimal(1).scaleb(-rule['decimal_places'])
    return value.quantize(quantum, rounding=_ROUNDING_MODES[rule['mode']])


def _quote(payload, store, *, simulator):
    quote_id = text_value(payload.get('quote_id'), 'quote_id')
    confirmer = approved_by(payload)
    line_rule = _load_rule(store, payload.get('line_rule_id'), 'line')
    tax_rule = _load_rule(store, payload.get('tax_rule_id'), 'tax_category_total')
    lines = payload.get('lines')
    if not isinstance(lines, list) or not lines:
        raise ValidationError('lines: 見積行を1件以上指定してください')
    tax_rates = payload.get('tax_rates')
    if not isinstance(tax_rates, dict) or not tax_rates:
        raise ValidationError('tax_rates: 人が指定した架空税率設定が必要です')
    rates = {}
    for tax_category, raw_rate in tax_rates.items():
        category = text_value(tax_category, 'tax_category')
        rate = decimal_value(raw_rate, f'tax_rates.{category}')
        if rate > 1:
            raise ValidationError(f'tax_rates.{category}: 税率は0〜1の十進比率で指定してください')
        rates[category] = rate

    quote_lines = []
    category_bases = {}
    seen_line_ids = set()
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            raise ValidationError(f'lines[{index}]: 見積行を確認してください')
        line_id = text_value(line.get('quote_line_id'), f'lines[{index}].quote_line_id')
        if line_id in seen_line_ids:
            raise ValidationError('quote_line_id: 重複しています')
        seen_line_ids.add(line_id)
        name = text_value(line.get('name'), f'lines[{index}].name')
        quantity = decimal_value(line.get('quantity'), f'lines[{index}].quantity')
        unit_price = decimal_value(line.get('unit_price'), f'lines[{index}].unit_price')
        tax_category = text_value(line.get('tax_category'), f'lines[{index}].tax_category')
        if tax_category not in rates:
            raise ValidationError(f'lines[{index}].tax_category: 税率の指定がありません')
        try:
            unrounded = quantity * unit_price
            rounded = _round(unrounded, line_rule)
        except InvalidOperation:
            raise ValidationError(f'lines[{index}]: 金額の桁数を確認してください') from None
        category_bases[tax_category] = category_bases.get(tax_category, Decimal('0')) + unrounded
        quote_lines.append({
            'quote_line_id': line_id, 'name': name, 'quantity': str(quantity),
            'unit_price': str(unit_price), 'unrounded_line_total': str(unrounded),
            'line_total': str(rounded), 'tax_category': tax_category,
            'rounding_rule': line_rule.copy(),
        })

    tax_groups = []
    for tax_category in sorted(category_bases):
        unrounded_tax = category_bases[tax_category] * rates[tax_category]
        try:
            tax_amount = _round(unrounded_tax, tax_rule)
        except InvalidOperation:
            raise ValidationError(f'{tax_category}: 税額の桁数を確認してください') from None
        tax_groups.append({
            'tax_category': tax_category,
            'tax_rate': str(rates[tax_category]),
            'unrounded_taxable_total': str(category_bases[tax_category]),
            'unrounded_tax': str(unrounded_tax), 'tax': str(tax_amount),
            'rounding_rule': tax_rule.copy(),
        })
    subtotal = sum((Decimal(line['line_total']) for line in quote_lines), Decimal('0'))
    tax_total = sum((Decimal(group['tax']) for group in tax_groups), Decimal('0'))
    quote = {
        'quote_id': quote_id, 'lines': quote_lines, 'subtotal': str(subtotal),
        'tax': str(tax_total), 'total': str(subtotal + tax_total),
        'tax_groups': tax_groups, 'confirmed_by': confirmer,
        'rounding_rules': {'line': line_rule.copy(), 'tax_category_total': tax_rule.copy()},
        'tax_rate_source': 'human_supplied_fictional_configuration',
        'simulator': simulator,
    }
    saved = store.put(QUOTE_NAMESPACE, quote, record_id=quote_id)
    return {'status': 'quoted', 'quote': saved, 'simulator': simulator,
            'notice': '税率は人が指定した架空設定です。法令・会計適合性を示すものではありません。'}
