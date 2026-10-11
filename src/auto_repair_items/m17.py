"""M17: compare an incoming price candidate with the current version."""

from decimal import Decimal

from .core import DEMO_DATE, ValidationError, approved_by, date_value, decimal_value, demo_item, text_value, validate_item


SPEC = {
    'idea_id': 'M17',
    'title': '更新差分確認画面',
    'description': '品目・単位・価格区分・仕入先・取引条件が一致する候補だけ価格差を比較し、人の採否を追記します。',
    'defaults': {
        'action': 'review',
        'item_id': 'demo-m17-paint',
        'candidate': {
            'item': demo_item('demo-m17-paint', '仕入', '88', 'ml'),
            'supplier_id': 'demo-supplier',
            'transaction_conditions': '月末締め翌月末払い',
            'valid_from': DEMO_DATE,
            'simulator': True,
        },
    },
}

_NAMESPACE = 'm17_update_reviews'


def run(payload: dict, store) -> dict:
    """Review one candidate; optionally record the human decision immediately."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    if payload.get('action', 'review') != 'review':
        raise ValidationError('action: reviewを選択してください')
    allowed = {'action', 'item_id', 'candidate', 'decision', 'confirmed_by', 'reason'}
    if set(payload) - allowed:
        raise ValidationError('payload: 指定できない項目があります')

    item_id = text_value(payload.get('item_id'), 'item_id')
    candidate = payload.get('candidate')
    if candidate is None and item_id == SPEC['defaults']['item_id']:
        candidate = SPEC['defaults']['candidate']
    comparison = _compare(item_id, candidate, store)
    decision = payload.get('decision')
    if decision is None:
        review = dict(item_id=item_id, decision='保留中', reviewer=None, reason=None,
                      comparison=comparison, candidate=candidate)
        saved = store.put(_NAMESPACE, review)
        return _response(saved, comparison)
    if decision not in ('採用', '保留'):
        raise ValidationError('decision: 採用または保留を選択してください')
    reviewer = approved_by(payload)
    reason = text_value(payload.get('reason'), 'reason')
    if decision == '採用' and not comparison['comparable']:
        raise ValidationError('比較不可: 条件不一致の候補は採用できません')

    record = dict(item_id=item_id, decision=decision, reviewer=reviewer,
                  reason=reason, comparison=comparison, candidate=candidate)
    with store.transaction():
        saved = store.put(_NAMESPACE, record)
        adopted_version = _adopt(candidate, reviewer, reason, store) if decision == '採用' else None
    result = _response(saved, comparison)
    if adopted_version:
        result['price_version_id'] = adopted_version['price_version_id']
        result['item'] = adopted_version['item']
    return result


def _compare(item_id, candidate, store):
    if not isinstance(candidate, dict):
        raise ValidationError('candidate: 取込候補が必要です')
    item = candidate.get('item')
    if not isinstance(item, dict) or item.get('item_id') != item_id:
        raise ValidationError('item_id: 現行品目と候補品目を一致させてください')
    item = validate_item(item)
    unit_price = decimal_value(item.get('unit_price'), 'candidate.unit_price')
    supplier_id = text_value(candidate.get('supplier_id'), 'candidate.supplier_id')
    conditions = text_value(candidate.get('transaction_conditions'), 'candidate.transaction_conditions')
    price_type = item.get('price_type')
    if price_type not in ('仕入', '販売'):
        raise ValidationError('candidate.price_type: 選択値を確認してください')

    versions = store.price_versions(item_id)
    old_version = versions[-1] if versions else None
    if old_version is None and item_id == SPEC['defaults']['item_id']:
        old_item = demo_item(item_id, '仕入', '80', 'ml')
        old_version = store.add_price(old_item, '架空デモ担当', supplier_id='demo-supplier',
                                      valid_from=DEMO_DATE, transaction_conditions='月末締め翌月末払い',
                                      currency='JPY', simulator=True, reason='架空デモ初回価格')
    if old_version is None:
        raise ValidationError('価格未確認: 比較する現行価格がありません')

    old_item = old_version['item']
    old_metadata = old_version.get('metadata') or {}
    old_conditions = old_metadata.get('transaction_conditions')
    candidate_currency = candidate.get('currency', 'JPY')
    old_currency = old_metadata.get('currency', 'JPY')
    keys_match = {
        'item_id': old_item['item_id'] == item_id,
        'name': old_item['name'] == item.get('name'),
        'category': old_item['category'] == item.get('category'),
        'unit': old_item['unit'] == item.get('unit'),
        'price_type': old_item['price_type'] == price_type,
        'supplier_id': old_version['supplier_id'] == supplier_id,
        'transaction_conditions': old_conditions == conditions,
        'currency': old_currency == candidate_currency,
    }
    comparable = all(keys_match.values())
    old_price = Decimal(old_item['unit_price'])
    difference = unit_price - old_price
    rate = difference / old_price * Decimal('100') if comparable and old_price != 0 else None
    if old_price == 0 and comparable:
        comparable = False
        keys_match['unit_price_base'] = False
    return {
        'comparable': comparable,
        'match_keys': keys_match,
        'old_price_version_id': old_version['price_version_id'],
        'old_unit_price': str(old_price),
        'candidate_unit_price': str(unit_price),
        'difference': str(difference) if comparable else None,
        'difference_rate_percent': str(rate) if comparable else None,
        'old_supplier_id': old_version['supplier_id'],
        'candidate_supplier_id': supplier_id,
        'old_transaction_conditions': old_conditions,
        'candidate_transaction_conditions': conditions,
        'old_source': old_item['source'],
        'candidate_source': item['source'],
        'simulator': bool(old_metadata.get('simulator') or candidate.get('simulator')),
    }


def _adopt(candidate, reviewer, reason, store):
    item = candidate['item']
    item = dict(item)
    item['updated_at'] = date_value(candidate.get('valid_from', item['updated_at']), 'valid_from').isoformat()
    return store.add_price(
        item, reviewer, supplier_id=text_value(candidate['supplier_id'], 'candidate.supplier_id'),
        valid_from=item['updated_at'], valid_until=candidate.get('valid_until'),
        status='approved', reason=reason,
        transaction_conditions=text_value(candidate['transaction_conditions'], 'candidate.transaction_conditions'),
        currency=candidate.get('currency', 'JPY'), simulator=bool(candidate.get('simulator', False)),
    )


def _response(saved, comparison):
    return {
        'status': 'saved', 'review_id': saved['record_id'], 'item_id': saved['item_id'],
        'decision': saved['decision'], 'confirmed_by': saved['reviewer'], 'reason': saved['reason'],
        'comparison': comparison,
    }
