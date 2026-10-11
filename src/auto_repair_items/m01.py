"""M01: preserve and normalize paint color codes without guessing prices."""

import json
import unicodedata

from .core import (
    DEMO_DATE,
    ValidationError,
    approved_by,
    date_value,
    text_value,
)


SPEC = {
    'idea_id': 'M01',
    'title': '塗料コード正規化',
    'description': '原表記と正規化コード、仕上げを分けて保持し、確認済みの品目単価だけを返します。',
    'defaults': {
        'action': 'register',
        'item_id': 'demo-paint',
        'maker': '架空メーカー',
        'raw_code': 'DEMO-001',
        'finish': 'メタリック',
        'price_type': '販売',
        'as_of': DEMO_DATE,
        'confirmed_by': '架空デモ担当',
    },
}


def normalize_code(raw_code: str) -> str:
    """Apply only format normalization; maker-specific code rules are unknown."""
    if not isinstance(raw_code, str) or not raw_code.strip():
        raise ValidationError('raw_code: 入力が必要です')
    normalized = unicodedata.normalize('NFKC', raw_code).strip().upper()
    if any(character.isspace() for character in normalized):
        raise ValidationError('raw_code: コード内の空白は曖昧なため確認が必要です')
    if any(unicodedata.category(character).startswith('C') for character in normalized):
        raise ValidationError('raw_code: 制御文字を含むコードは使用できません')
    if not any(character.isalnum() for character in normalized):
        raise ValidationError('raw_code: 英数字を含むコードが必要です')
    return normalized


def _mapping_id(maker: str, normalized_code: str, finish: str) -> str:
    return json.dumps([maker, normalized_code, finish], ensure_ascii=False, separators=(',', ':'))


def _mapping_fields(payload: dict) -> tuple[str, str, str, str]:
    maker = text_value(payload.get('maker'), 'maker')
    raw_code = payload.get('raw_code')
    if not isinstance(raw_code, str) or not raw_code.strip():
        raise ValidationError('raw_code: 入力が必要です')
    finish = text_value(payload.get('finish'), 'finish')
    if any(unicodedata.category(character).startswith('C') for value in (maker, finish) for character in value):
        raise ValidationError('maker / finish: 制御文字は使用できません')
    normalized_code = normalize_code(raw_code)
    return maker, raw_code, normalized_code, finish


def run(payload: dict, store) -> dict:
    """Register a human-confirmed code mapping or look up its approved item."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')

    action = payload.get('action', 'register')
    if action == 'register':
        return _register(payload, store)
    if action == 'lookup':
        return _lookup(payload, store)
    raise ValidationError('action: register または lookup を選択してください')


def _register(payload: dict, store) -> dict:
    maker, raw_code, normalized_code, finish = _mapping_fields(payload)
    item_id = text_value(payload.get('item_id'), 'item_id')
    price_type = text_value(payload.get('price_type', '販売'), 'price_type')
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    confirmer = approved_by(payload)

    # Resolve only an existing approved price. A color or code never creates a price.
    version = store.get_price(item_id, price_type, as_of=as_of)
    item = version['item']
    if item['category'] != '塗料':
        raise ValidationError('category: 塗料の品目を選択してください')

    mapping_id = _mapping_id(maker, normalized_code, finish)
    existing = store.records('paint_code', mapping_id)
    same_mapping = bool(existing and all(
        all(record.get(key) == value for key, value in {
            'maker': maker,
            'raw_code': raw_code,
            'normalized_code': normalized_code,
            'finish': finish,
            'item_id': item_id,
        }.items()) for record in existing
    ))

    # Different source spellings or item identities can collapse under a generic
    # normalization. Keep such records pending until the maker's rule is verified.
    collision = bool(existing and not same_mapping)
    status = 'pending' if collision else 'approved'
    record = {
        'maker': maker,
        'raw_code': raw_code,
        'normalized_code': normalized_code,
        'finish': finish,
        'item_id': item_id,
        'status': status,
        'confirmed_by': confirmer,
        'reason': '正規化コードの対応を人が確認' if status == 'approved' else '正規化後の対応が曖昧なため要確認',
    }
    if not same_mapping or existing[-1].get('status') != status:
        with store.transaction():
            store.put('paint_code', record, record_id=mapping_id)

    if status != 'approved':
        return {
            'status': status,
            'paint_code': record,
            'items': [],
            'reason': record['reason'],
        }
    return {
        'status': status,
        'paint_code': record,
        'item': item,
        'items': [item],
        'price_version_id': version['price_version_id'],
    }


def _lookup(payload: dict, store) -> dict:
    maker, raw_code, normalized_code, finish = _mapping_fields(payload)
    price_type = text_value(payload.get('price_type', '販売'), 'price_type')
    as_of = date_value(payload.get('as_of', DEMO_DATE), 'as_of').isoformat()
    mapping_id = _mapping_id(maker, normalized_code, finish)
    mappings = store.records('paint_code', mapping_id)
    if not mappings:
        raise ValidationError('paint_code: 登録済みの対応がありません')
    mapping = mappings[-1]
    if mapping['status'] != 'approved' or mapping['raw_code'] != raw_code:
        raise ValidationError('paint_code: 原表記または対応が未確認です')
    version = store.get_price(mapping['item_id'], price_type, as_of=as_of)
    item = version['item']
    if item['category'] != '塗料':
        raise ValidationError('category: 塗料の品目を選択してください')
    mapping = {key: value for key, value in mapping.items() if key != 'record_id'}
    return {
        'status': 'approved',
        'paint_code': mapping,
        'item': item,
        'items': [item],
        'price_version_id': version['price_version_id'],
    }
