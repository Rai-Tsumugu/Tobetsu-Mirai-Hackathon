"""M12: review mocked OCR candidates field by field before price registration."""

from .core import (CATEGORIES, DEMO_DATE, ITEM_FIELDS, PRICE_TYPES, ValidationError,
                   approved_by, date_value, decimal_value, text_value, validate_item)


CONFIDENCE_THRESHOLD = 0.8
_DEMO_FIELDS = {
    'item_id': {'value': 'demo-m12-thinner', 'confidence': '0.99'},
    'name': {'value': '架空デモ溶剤', 'confidence': '0.96'},
    'category': {'value': '溶剤', 'confidence': '0.99'},
    'unit': {'value': 'L', 'confidence': '0.98'},
    'unit_price': {'value': '480', 'confidence': '0.94'},
    'price_type': {'value': '仕入', 'confidence': '0.97'},
    'source': {'value': 'simulator:架空OCR価格票', 'confidence': '0.92'},
    'updated_at': {'value': DEMO_DATE, 'confidence': '0.95'},
}

SPEC = {
    'idea_id': 'M12',
    'title': 'OCR候補・人確認キュー',
    'description': 'mock OCRの品目候補を項目ごとに確認し、全項目を人が確定した場合だけ価格登録します。',
    'defaults': {
        'action': 'stage',
        'source_key': 'demo-m12-ocr',
        'ocr_fields': _DEMO_FIELDS,
        'source': 'simulator:架空OCR',
    },
}


def run(payload: dict, store) -> dict:
    """Stage a mock OCR result or append a review and register when complete."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'stage')
    if action == 'stage':
        if set(payload) - {'action', 'source_key', 'ocr_fields', 'source'}:
            raise ValidationError('payload: OCR原文や未対応のデータは受け付けません')
        return _stage(payload, store)
    if action == 'review':
        if set(payload) - {'action', 'candidate_id', 'fields', 'confirmed_by'}:
            raise ValidationError('payload: OCR原文や未対応のデータは受け付けません')
        return _review(payload, store)
    raise ValidationError('action: stage または review を指定してください')


def _stage(payload, store):
    source_key = text_value(payload.get('source_key'), 'source_key')
    if len(source_key) > 128:
        raise ValidationError('source_key: 128文字以下にしてください')
    source = text_value(payload.get('source', 'simulator:架空OCR'), 'source')
    fields = payload.get('ocr_fields')
    if not isinstance(fields, dict) or set(fields) - set(ITEM_FIELDS):
        raise ValidationError('ocr_fields: 共通品目項目の候補を指定してください')

    # Only field candidates are accepted; full invoice/image text is never kept.
    candidates = {}
    for field in ITEM_FIELDS:
        candidate = fields.get(field)
        value = None
        confidence = None
        if isinstance(candidate, dict):
            raw_value = candidate.get('value')
            raw_confidence = candidate.get('confidence')
            if raw_value is not None and isinstance(raw_value, str):
                value = raw_value.strip() or None
            try:
                number = float(raw_confidence)
                if 0 <= number <= 1:
                    confidence = str(raw_confidence)
            except (TypeError, ValueError, OverflowError):
                pass
        if confidence is None or float(confidence) < CONFIDENCE_THRESHOLD or value is None:
            value = None
        candidates[field] = {'candidate_value': value, 'confidence': confidence}

    queue = store.put('m12_ocr_queue', {
        'source_key': source_key,
        'source': source,
        'candidates': candidates,
        'corrected_values': {},
        'confirmed_fields': [],
        'reviewer': None,
        'status': 'pending',
        'ocr_connected': False,
        'simulator': True,
    })
    return {
        'status': '人の確認待ち',
        'candidate_id': queue['record_id'],
        'candidates': candidates,
        'confirmed_fields': [],
        'missing_fields': list(ITEM_FIELDS),
        'items': [],
        'simulator': True,
        'ocr_connected': False,
        'message': 'OCRはmock読取候補です。実画像OCRは未接続です。',
    }


def _review(payload, store):
    candidate_id = text_value(payload.get('candidate_id'), 'candidate_id')
    reviewer = approved_by(payload)
    raw_updates = payload.get('fields')
    if not isinstance(raw_updates, dict) or not raw_updates:
        raise ValidationError('fields: 確認する項目を指定してください')
    if set(raw_updates) - set(ITEM_FIELDS):
        raise ValidationError('fields: 共通品目項目だけ確認できます')

    queue = store.latest('m12_ocr_queue', candidate_id)
    if queue['status'] == 'approved':
        raise ValidationError('この候補はすでに登録されています')

    corrected_values = dict(queue['corrected_values'])
    confirmed_fields = set(queue['confirmed_fields'])
    updates = {}
    for field, update in raw_updates.items():
        if not isinstance(update, dict) or update.get('confirmed') is not True:
            raise ValidationError(f'{field}: 人の確認を明示してください')
        value = update.get('corrected_value')
        if value is None or not isinstance(value, str) or not value.strip():
            raise ValidationError(f'{field}: 確認済みの値を入力してください')
        value = value.strip()
        _validate_field(field, value)
        # Store only the canonical field and its corrected value, never source text.
        updates[field] = value
        corrected_values[field] = value
        confirmed_fields.add(field)

    if 'source' not in corrected_values:
        corrected_values['source'] = queue['source']
    missing_fields = [field for field in ITEM_FIELDS if field not in confirmed_fields]
    status = 'pending'
    registered = None
    if not missing_fields:
        item = validate_item(corrected_values)
        version = store.add_price(item, reviewer, reason='OCR候補の全必須欄を人が確認', ocr_candidate_id=candidate_id)
        registered = version['item']
        status = 'approved'

    with store.transaction():
        store.put('m12_ocr_review', {
            'candidate_id': candidate_id,
            'corrected_value': updates,
            'confirmed_fields': sorted(updates),
            'reviewer': reviewer,
            'status': status,
        }, record_id=candidate_id)
        store.put('m12_ocr_queue', {
            'source_key': queue['source_key'],
            'source': queue['source'],
            'candidates': queue['candidates'],
            'corrected_values': corrected_values,
            'confirmed_fields': sorted(confirmed_fields),
            'reviewer': reviewer,
            'status': status,
            'ocr_connected': False,
            'simulator': True,
        }, record_id=candidate_id)

    result = {
        'status': 'approved' if registered else '人の確認待ち',
        'candidate_id': candidate_id,
        'corrected_value': updates,
        'confirmed_fields': sorted(confirmed_fields),
        'missing_fields': missing_fields,
        'reviewer': reviewer,
        'items': [registered] if registered else [],
        'simulator': True,
        'ocr_connected': False,
    }
    if registered:
        result['price_version_id'] = version['price_version_id']
    return result


def _validate_field(field, value):
    if field == 'unit_price':
        decimal_value(value, field)
    elif field == 'updated_at':
        date_value(value, field)
    elif field == 'category' and value not in CATEGORIES:
        raise ValidationError('category: 選択値を確認してください')
    elif field == 'price_type' and value not in PRICE_TYPES:
        raise ValidationError('price_type: 選択値を確認してください')
    else:
        text_value(value, field)
