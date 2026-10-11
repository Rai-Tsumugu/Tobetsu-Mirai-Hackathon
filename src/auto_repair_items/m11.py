"""M11: stage fictional PDF line candidates from a user-selected page region."""

from datetime import datetime, timezone
from decimal import Decimal

from .core import DEMO_DATE, ValidationError, approved_by, decimal_value, text_value
from .importing import approve_rows, stage_rows


SPEC = {
    'idea_id': 'M11',
    'title': 'PDF伝票領域指定取込',
    'description': '人が指定したページ領域からSimulatorの架空明細候補を作り、選択承認した行だけ価格マスタへ登録します。',
    'defaults': {
        'action': 'sample',
        'confirmed_by': '架空デモ担当',
    },
}

_SAMPLE_ROWS = [{
    'item_id': 'demo-m11-paint', 'name': '架空サンプル塗料', 'category': '塗料',
    'unit': 'ml', 'unit_price': '95', 'price_type': '仕入',
    'source': 'simulator:架空PDF明細', 'updated_at': DEMO_DATE,
}]
_MAX_PAGE = 10000


def run(payload: dict, store) -> dict:
    """Create mock candidates from a region reference, or approve selected rows."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'stage')
    if action == 'approve':
        batch_id = text_value(payload.get('import_batch_id'), 'import_batch_id')
        batch = store.latest('import_batch', batch_id)
        ids = payload.get('candidate_ids')
        if not isinstance(ids, list) or any(candidate_id not in batch['candidate_ids'] for candidate_id in ids):
            raise ValidationError('candidate_ids: このPDF候補から承認対象を選択してください')
        result = approve_rows(store, ids, approved_by(payload))
        result['import_batch_id'] = batch_id
        result['simulator'] = True
        return result
    if action not in ('stage', 'sample'):
        raise ValidationError('action: stage / sample / approve を指定してください')

    if action == 'sample':
        document_id = 'demo-m11-pdf'
        page = 1
        page_width, page_height = Decimal('612'), Decimal('792')
        region = {'x': Decimal('36'), 'y': Decimal('120'), 'width': Decimal('540'), 'height': Decimal('240')}
        rows = _SAMPLE_ROWS
    else:
        document_id = _document_reference(payload.get('source_document_id'))
        page = _page_number(payload.get('page'))
        page_width = decimal_value(payload.get('page_width'), 'page_width', positive=True)
        page_height = decimal_value(payload.get('page_height'), 'page_height', positive=True)
        region = _region(payload.get('region'), page_width, page_height)
        # Extraction is deliberately simulated: no PDF bytes are read or stored.
        rows = _SAMPLE_ROWS

    source = 'simulator:未接続のPDF抽出、架空値'
    rows = [dict(row, source=source) for row in rows]
    staged = stage_rows(store, rows, source)
    batch = store.put('import_batch', {
        'source_document_id': document_id,
        'document_type': 'pdf',
        'page': page,
        'page_width': str(page_width),
        'page_height': str(page_height),
        'region': {key: str(value) for key, value in region.items()},
        'candidate_ids': [row['record_id'] for row in staged['staged_rows']],
        'imported_at': datetime.now(timezone.utc).isoformat(),
        'simulator': True,
        'extraction_connected': False,
    })
    return {
        'status': '人の確認待ち',
        'source_document_id': document_id,
        'page': page,
        'region': {key: str(value) for key, value in region.items()},
        'import_batch_id': batch['record_id'],
        'staged_rows': staged['staged_rows'],
        'items': [],
        'simulator': True,
        'extraction_connected': False,
    }


def _document_reference(value):
    value = text_value(value, 'source_document_id')
    if len(value) > 128 or any(ord(char) < 32 for char in value):
        raise ValidationError('source_document_id: 参照IDは128文字以下で指定してください')
    return value


def _page_number(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_PAGE:
        raise ValidationError('page: 1〜10000の整数を指定してください')
    return value


def _region(value, page_width, page_height):
    keys = ('x', 'y', 'width', 'height')
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValidationError('region: x / y / width / height を指定してください')
    bounds = {key: decimal_value(value[key], f'region.{key}', positive=key in ('width', 'height'))
              for key in keys}
    if bounds['x'] + bounds['width'] > page_width or bounds['y'] + bounds['height'] > page_height:
        raise ValidationError('region: ページ範囲内の領域を指定してください')
    return bounds
