"""M28: versioned, human-approved markup suggestions for purchase prices."""

from decimal import Decimal
from uuid import uuid4

from .core import DEMO_DATE, ValidationError, approved_by, date_value, decimal_value, text_value


SPEC = {
    'idea_id': 'M28',
    'title': '掛率ルールの版管理',
    'description': 'カテゴリ・仕入先・適用日ごとの掛率を版管理し、販売価格候補を人の承認後にだけ登録します。',
    'defaults': {
        'action': 'record_rule', 'rule_id': 'demo-markup', 'category': '塗料',
        'supplier_id': 'demo-supplier', 'effective_from': DEMO_DATE,
        'multiplier': '1.5', 'confirmed_by': '架空デモ担当',
        'reason': '架空デモ用のルール登録',
    },
}

RULES = 'markup_rule'
PROPOSALS = 'markup_proposal'


def run(payload: dict, store) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'propose')
    if action == 'record_rule':
        _keys(payload, {'action', 'rule_id', 'category', 'supplier_id', 'effective_from',
                        'multiplier', 'confirmed_by', 'reason'})
        return {'rule': _record_rule(payload, store)}
    if action == 'list_rules':
        _keys(payload, {'action', 'rule_id'})
        rules = store.records(RULES, payload.get('rule_id'))
        return {'rules': rules, 'simulator': any(rule.get('simulator') for rule in rules)}
    if action == 'propose':
        _keys(payload, {'action', 'item_id', 'purchase_price_version_id', 'rule_id',
                        'as_of', 'reason', 'confirmed_by'})
        return _propose(payload, store)
    if action == 'approve':
        _keys(payload, {'action', 'proposal_id', 'confirmed_by', 'reason'})
        return _approve(payload, store)
    if action == 'list_proposals':
        _keys(payload, {'action'})
        return {'proposals': store.records(PROPOSALS), 'simulator': False}
    raise ValidationError('action: record_rule / list_rules / propose / approve / list_proposals を選択してください')


def _keys(payload, allowed):
    if set(payload) - allowed:
        raise ValidationError('payload: 指定できない項目があります')


def _record_rule(payload, store):
    rule_id = text_value(payload.get('rule_id'), 'rule_id')
    category = text_value(payload.get('category'), 'category')
    if category not in ('部品', '塗料', '溶剤', '消耗品'):
        raise ValidationError('category: 選択値を確認してください')
    supplier_id = text_value(payload.get('supplier_id'), 'supplier_id')
    effective_from = date_value(payload.get('effective_from'), 'effective_from').isoformat()
    multiplier = decimal_value(payload.get('multiplier'), 'multiplier', positive=True)
    confirmer = approved_by(payload)
    reason = text_value(payload.get('reason'), 'reason')
    previous = store.records(RULES, rule_id)
    if previous:
        latest = previous[-1]
        if latest['effective_from'] > effective_from:
            raise ValidationError('effective_from: 既存ルールより前の日付です')
        if (latest['category'], latest['supplier_id']) != (category, supplier_id):
            raise ValidationError('rule_id: ルールの対象カテゴリ・仕入先は変更できません')
    record = {
        'rule_id': rule_id, 'version': len(previous) + 1,
        'category': category, 'supplier_id': supplier_id,
        'effective_from': effective_from, 'multiplier': str(multiplier),
        'confirmed_by': confirmer, 'reason': reason,
    }
    store.put(RULES, record, record_id=rule_id)
    return record


def _propose(payload, store):
    item_id = text_value(payload.get('item_id'), 'item_id')
    purchase_id = text_value(payload.get('purchase_price_version_id'), 'purchase_price_version_id')
    rule_id = text_value(payload.get('rule_id'), 'rule_id')
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    reason = text_value(payload.get('reason'), 'reason')
    purchase = _price_by_id(store, item_id, purchase_id, '仕入')
    item = purchase['item']
    eligible = [r for r in store.records(RULES, rule_id)
                if r['category'] == item['category']
                and r['supplier_id'] == purchase.get('supplier_id', '')
                and r['effective_from'] <= as_of]
    if not eligible:
        raise ValidationError('掛率ルール: 対象カテゴリ・仕入先・適用日の承認済みルールがありません')
    rule = max(enumerate(eligible), key=lambda pair: (pair[1]['effective_from'], pair[0]))[1]
    if purchase['status'] != 'approved' or purchase['valid_from'] > as_of or (
            purchase['valid_until'] is not None and as_of > purchase['valid_until']):
        raise ValidationError('仕入価格版: 指定日で有効な承認済み価格が必要です')
    _ensure_no_sales(store, item_id, as_of, purchase.get('supplier_id', ''))
    candidate_amount = Decimal(item['unit_price']) * Decimal(rule['multiplier'])
    candidate = dict(item, unit_price=str(candidate_amount), price_type='販売',
                     source=f"simulator:markup:{rule_id}:v{rule['version']}", updated_at=as_of)
    proposal_id = uuid4().hex
    proposal = {
        'proposal_id': proposal_id, 'item_id': item_id, 'category': item['category'],
        'supplier_id': purchase.get('supplier_id', ''), 'as_of': as_of,
        'purchase_price_version_id': purchase_id, 'purchase_unit_price': item['unit_price'],
        'rule_id': rule_id, 'rule_version': rule['version'],
        'multiplier': rule['multiplier'], 'candidate': candidate,
        'reason': reason, 'status': 'pending', 'simulator': item['source'].startswith('simulator:'),
    }
    store.put(PROPOSALS, proposal, record_id=proposal_id)
    return {'proposal': proposal, 'items': [candidate], 'price_saved': False,
            'notice': '販売価格候補です。人が承認するまで価格マスタへ保存されません。'}


def _approve(payload, store):
    proposal_id = text_value(payload.get('proposal_id'), 'proposal_id')
    confirmer = approved_by(payload)
    reason = text_value(payload.get('reason'), 'reason')
    proposal = store.latest(PROPOSALS, proposal_id)
    if proposal['status'] != 'pending':
        raise ValidationError('proposal: 承認待ちの候補ではありません')
    _ensure_no_sales(store, proposal['item_id'], proposal['as_of'], proposal['supplier_id'])
    purchase = _price_by_id(store, proposal['item_id'], proposal['purchase_price_version_id'], '仕入')
    rule_versions = [r for r in store.records(RULES, proposal['rule_id'])
                     if r['version'] == proposal['rule_version']]
    if not rule_versions or rule_versions[0]['multiplier'] != proposal['multiplier']:
        raise ValidationError('掛率ルール版: 提案時の版を確認できません')
    candidate = proposal['candidate']
    version = store.add_price(
        candidate, confirmer, supplier_id=proposal['supplier_id'],
        valid_from=proposal['as_of'], reason=reason,
        markup_rule_id=proposal['rule_id'], markup_rule_version=proposal['rule_version'],
        purchase_price_version_id=purchase['price_version_id'], proposal_id=proposal_id,
        multiplier=proposal['multiplier'], target_category=proposal['category'],
        applied_on=proposal['as_of'],
    )
    approved = dict(proposal, status='approved', approved_by=confirmer,
                    approval_reason=reason, sales_price_version_id=version['price_version_id'])
    store.put(PROPOSALS, approved, record_id=proposal_id)
    return {'proposal': approved, 'price_version': version,
            'items': [version['item']], 'price_saved': True}


def _price_by_id(store, item_id, price_version_id, price_type):
    for version in store.price_versions(item_id, price_type):
        if version['price_version_id'] == price_version_id:
            return version
    raise ValidationError(f'{price_type}価格版: 品目に紐づく指定版がありません')


def _ensure_no_sales(store, item_id, as_of, supplier_id):
    # A sales price is item-level for this rule; a different supplier must not
    # make an already-priced item eligible for another markup pass.
    existing = [v for v in store.price_versions(item_id, '販売') if v['status'] == 'approved']
    if existing:
        raise ValidationError('販売価格が既にあるため、掛率を再適用できません')
