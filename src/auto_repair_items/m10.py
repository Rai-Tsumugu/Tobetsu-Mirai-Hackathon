"""M10: stage a fixed-column, single-sheet XLSX price import for review."""

import base64
import binascii
from io import BytesIO
import posixpath
import re
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from .core import DEMO_DATE, ITEM_FIELDS, ValidationError, approved_by, text_value
from .importing import approve_rows, stage_rows


SPEC = {
    'idea_id': 'M10',
    'title': 'Excel単一シート取込',
    'description': '固定8列の1シートXLSXを候補として隔離し、人が確認した行だけ価格マスタへ登録します。',
    'defaults': {
        'action': 'sample',
        'confirmed_by': '架空デモ担当',
    },
}

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_ZIP_ENTRIES = 100
MAX_ROWS = 1000
_MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_DOC_REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_PKG_REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
_CONTENT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'


def run(payload: dict, store) -> dict:
    """Generate a fictional sample, stage uploaded XLSX rows, or approve staged rows."""
    if not isinstance(payload, dict):
        raise ValidationError('payload: 入力を確認してください')
    action = payload.get('action', 'stage')
    if action == 'approve':
        batch_id = text_value(payload.get('import_batch_id'), 'import_batch_id')
        result = approve_rows(store, payload.get('candidate_ids'), approved_by(payload))
        result['import_batch_id'] = batch_id
        return result
    if action == 'sample':
        file_bytes = _sample_xlsx()
        file_name = '架空サンプル.xlsx'
        source = 'simulator:架空値、架空Excelサンプル'
    elif action == 'stage':
        file_name = _safe_file_name(payload.get('file_name'))
        file_bytes = _decode_file(payload.get('file_base64'))
        source = f'excel:{file_name}'
    else:
        raise ValidationError('action: stage / sample / approve を指定してください')

    rows = _read_xlsx(file_bytes)
    staged = stage_rows(store, rows, source, field_map={field: field for field in ITEM_FIELDS})
    batch = store.put('import_batch', {
        'file_name': file_name,
        'source': source,
        'row_count': len(rows),
        'staged_count': len(staged['staged_rows']),
        'simulator': action == 'sample',
    })
    return {
        'status': '人の確認待ち',
        'import_batch_id': batch['record_id'],
        'file_name': file_name,
        'row_count': len(rows),
        'staged_rows': staged['staged_rows'],
        'items': [],
        'simulator': action == 'sample',
    }


def _safe_file_name(value):
    name = text_value(value, 'file_name')
    if '/' in name or '\\' in name or name in ('.', '..') or not name.lower().endswith('.xlsx'):
        raise ValidationError('file_name: .xlsx形式のファイル名を指定してください')
    return name


def _decode_file(value):
    if not isinstance(value, str) or not value or len(value) > (MAX_FILE_BYTES * 4 // 3 + 8):
        raise ValidationError('file_base64: サイズ上限内のXLSXデータが必要です')
    if value.startswith('data:'):
        header, separator, value = value.partition(',')
        if not separator or ';base64' not in header.lower():
            raise ValidationError('file_base64: base64形式を確認してください')
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError('file_base64: base64形式を確認してください') from None
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValidationError('file_base64: ファイルは5MB以下にしてください')
    return data


def _xml(data, label):
    try:
        # Reject DTD/entity declarations; XLSX requires no document type declarations.
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            raise ValidationError(f'{label}: DTD / entity は使用できません')
        return ET.fromstring(data)
    except ET.ParseError:
        raise ValidationError(f'{label}: XLSX内のXMLを読み取れません') from None


def _read_xlsx(data):
    try:
        archive = ZipFile(BytesIO(data))
    except (BadZipFile, OSError):
        raise ValidationError('XLSX: 正しいExcelファイルではありません') from None
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES or sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
            raise ValidationError('XLSX: 展開サイズまたはファイル数の上限を超えています')
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or any(name.startswith('/') or '..' in name.split('/') for name in names):
            raise ValidationError('XLSX: ZIP内のパスを確認してください')
        if any(name.lower().endswith(('.xlsm', '.bin')) or 'vbaproject' in name.lower() for name in names):
            raise ValidationError('XLSX: マクロを含むファイルは取り込めません')
        required = {'[Content_Types].xml', '_rels/.rels', 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels'}
        if not required.issubset(names):
            raise ValidationError('XLSX: 必須構成が不足しています')
        contents = _xml(archive.read('[Content_Types].xml'), 'Content_Types')
        if any('macroenabled' in node.attrib.get('ContentType', '').lower() for node in contents):
            raise ValidationError('XLSX: マクロ有効形式は取り込めません')
        for name in names:
            if name.endswith('.rels'):
                root = _xml(archive.read(name), name)
                for rel in root.findall(f'{{{_PKG_REL_NS}}}Relationship'):
                    if rel.attrib.get('TargetMode') == 'External':
                        raise ValidationError('XLSX: 外部リンクを含むファイルは取り込めません')
                    target = rel.attrib.get('Target', '')
                    if not target or target.startswith(('http:', 'https:', '//')) or '?' in target or '#' in target:
                        raise ValidationError('XLSX: 安全でないリンク先を含んでいます')
                    rel_dir = posixpath.dirname(name[:-5])
                    resolved_target = posixpath.normpath(posixpath.join(rel_dir, target.lstrip('/')))
                    if resolved_target == '..' or resolved_target.startswith('../'):
                        raise ValidationError('XLSX: ZIP外を指すリンク先は使用できません')

        workbook = _xml(archive.read('xl/workbook.xml'), 'workbook')
        sheets = workbook.findall(f'.//{{{_MAIN_NS}}}sheet')
        if len(sheets) != 1:
            raise ValidationError('XLSX: ワークシートは1枚だけにしてください')
        sheet_rel_id = sheets[0].attrib.get(f'{{{_DOC_REL_NS}}}id')
        rel_root = _xml(archive.read('xl/_rels/workbook.xml.rels'), 'workbook relationships')
        sheet_rel = next((rel for rel in rel_root.findall(f'{{{_PKG_REL_NS}}}Relationship')
                          if rel.attrib.get('Id') == sheet_rel_id), None)
        if sheet_rel is None or 'worksheet' not in sheet_rel.attrib.get('Type', ''):
            raise ValidationError('XLSX: 対象シートを特定できません')
        target = sheet_rel.attrib.get('Target', '')
        if target.startswith('/'):
            sheet_path = target.lstrip('/')
        else:
            sheet_path = posixpath.normpath(posixpath.join('xl', target))
        if sheet_path.startswith('../') or sheet_path not in names:
            raise ValidationError('XLSX: 対象シートのパスが不正です')

        shared = []
        if 'xl/sharedStrings.xml' in names:
            shared_root = _xml(archive.read('xl/sharedStrings.xml'), 'shared strings')
            shared = [''.join(node.itertext()) for node in shared_root.findall(f'{{{_MAIN_NS}}}si')]
        root = _xml(archive.read(sheet_path), 'worksheet')
        if root.find(f'.//{{{_MAIN_NS}}}mergeCells') is not None:
            raise ValidationError('XLSX: 結合セルは取り込めません')
        if root.find(f'.//{{{_MAIN_NS}}}hyperlinks') is not None:
            raise ValidationError('XLSX: ハイパーリンクを含むファイルは取り込めません')
        data_rows = root.findall(f'.//{{{_MAIN_NS}}}sheetData/{{{_MAIN_NS}}}row')
        if not data_rows or len(data_rows) > MAX_ROWS + 1:
            raise ValidationError('XLSX: ヘッダーと1〜1000件のデータ行が必要です')
        rows = []
        for row_index, row_node in enumerate(data_rows):
            values = {}
            for cell in row_node.findall(f'{{{_MAIN_NS}}}c'):
                address = cell.attrib.get('r', '')
                match = re.match(r'^([A-Z]+)', address)
                if not match:
                    raise ValidationError('XLSX: セル位置を読み取れません')
                column = _column_index(match.group(1))
                if column in values:
                    raise ValidationError('XLSX: 同じ行に重複セルがあります')
                if cell.find(f'{{{_MAIN_NS}}}f') is not None:
                    raise ValidationError('XLSX: 数式セルは取り込めません')
                if column >= len(ITEM_FIELDS):
                    raise ValidationError('XLSX: 8列を超えるデータは取り込めません')
                values[column] = _cell_value(cell, shared)
            if row_index == 0:
                header = [values.get(index, '') for index in range(len(ITEM_FIELDS))]
                if header != list(ITEM_FIELDS) or len(values) != len(ITEM_FIELDS):
                    raise ValidationError('XLSX: 1行目は共通8項目の固定ヘッダーにしてください')
                continue
            if not values or all(value == '' for value in values.values()):
                continue
            rows.append({field: values.get(index, '') for index, field in enumerate(ITEM_FIELDS)})
        if not rows:
            raise ValidationError('XLSX: データ行がありません')
        return rows


def _column_index(letters):
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter) - ord('A') + 1
    return value - 1


def _cell_value(cell, shared):
    kind = cell.attrib.get('t')
    value_node = cell.find(f'{{{_MAIN_NS}}}v')
    if kind == 'inlineStr':
        return ''.join(cell.find(f'{{{_MAIN_NS}}}is').itertext()) if cell.find(f'{{{_MAIN_NS}}}is') is not None else ''
    if value_node is None or value_node.text is None:
        return ''
    value = value_node.text
    if kind == 's':
        try:
            return shared[int(value)]
        except (ValueError, IndexError):
            raise ValidationError('XLSX: shared string index が不正です') from None
    if kind == 'b':
        raise ValidationError('XLSX: 真偽値セルは取り込めません')
    return value


def _sample_xlsx():
    """Build a tiny fictional standards-compliant workbook for the demo."""
    from zipfile import ZIP_DEFLATED

    headers = ITEM_FIELDS
    sample = ('demo-m10-thinner', '架空サンプルシンナー', '溶剤', 'ml', '35', '仕入', 'simulator:架空値', DEMO_DATE)
    inline = lambda ref, val: f'<c r="{ref}" t="inlineStr"><is><t>{_xml_escape(val)}</t></is></c>'
    header_cells = ''.join(inline(f'{chr(65 + i)}1', value) for i, value in enumerate(headers))
    cells = ''.join(inline(f'{chr(65 + i)}2', value) for i, value in enumerate(sample))
    worksheet = ('<?xml version="1.0" encoding="UTF-8"?>'
                 '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                 f'<sheetData><row r="1">{header_cells}</row><row r="2">{cells}</row></sheetData></worksheet>')
    workbook = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Items" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 '</Relationships>')
    types = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
             '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
             '</Types>')
    stream = BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as archive:
        for name, content in (('[Content_Types].xml', types), ('_rels/.rels', root_rels),
                              ('xl/workbook.xml', workbook), ('xl/_rels/workbook.xml.rels', rels),
                              ('xl/worksheets/sheet1.xml', worksheet)):
            archive.writestr(name, content)
    return stream.getvalue()


def _xml_escape(value):
    return (str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&apos;'))
