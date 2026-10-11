"""M10 XLSX import safety, staging, and human approval tests."""

import base64
from io import BytesIO
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from auto_repair_items import m10
from auto_repair_items.core import ITEM_FIELDS, Store, ValidationError


class M10Tests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def make_workbook(self, edits=None, extra=None):
        source = ZipFile(BytesIO(m10._sample_xlsx()))
        contents = {name: source.read(name) for name in source.namelist()}
        source.close()
        for name, transform in (edits or {}).items():
            contents[name] = transform(contents[name])
        contents.update(extra or {})
        output = BytesIO()
        with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
            for name, content in contents.items():
                archive.writestr(name, content)
        return output.getvalue()

    def stage_payload(self, data, **changes):
        payload = {
            'action': 'stage',
            'file_name': 'fictional.xlsx',
            'file_base64': base64.b64encode(data).decode('ascii'),
        }
        payload.update(changes)
        return payload

    def test_defaults_generate_fictional_xlsx_and_stage_without_master_writes(self):
        result = m10.run(m10.SPEC['defaults'], self.store)

        self.assertTrue(result['simulator'])
        self.assertEqual(result['file_name'], '架空サンプル.xlsx')
        self.assertEqual(result['row_count'], 1)
        self.assertEqual(result['staged_rows'][0]['status'], 'pending')
        self.assertEqual(result['items'], [])
        self.assertEqual(self.store.price_versions(), [])
        batch = self.store.latest('import_batch', result['import_batch_id'])
        self.assertTrue(batch['simulator'])

    def test_base64_file_stages_fixed_eight_fields_then_only_human_approval_saves(self):
        result = m10.run(self.stage_payload(m10._sample_xlsx()), self.store)
        candidate_id = result['staged_rows'][0]['record_id']

        self.assertEqual(result['status'], '人の確認待ち')
        self.assertEqual(set(result['staged_rows'][0]['item']), set(ITEM_FIELDS))
        self.assertEqual(self.store.price_versions(), [])
        approved = m10.run({
            'action': 'approve',
            'candidate_ids': [candidate_id],
            'confirmed_by': '人間確認者',
            'import_batch_id': result['import_batch_id'],
        }, self.store)
        self.assertEqual(approved['items'][0]['item_id'], 'demo-m10-thinner')
        self.assertEqual(self.store.price_versions()[0]['confirmed_by'], '人間確認者')

    def test_invalid_row_is_quarantined_and_cannot_be_approved(self):
        invalid = self.make_workbook({'xl/worksheets/sheet1.xml':
                                     lambda xml: xml.replace(b'>35<', b'>-1<')})
        result = m10.run(self.stage_payload(invalid), self.store)
        candidate = result['staged_rows'][0]
        self.assertEqual(candidate['status'], 'quarantined')
        with self.assertRaises(ValidationError):
            m10.run({
                'action': 'approve', 'candidate_ids': [candidate['record_id']],
                'confirmed_by': '人間確認者', 'import_batch_id': result['import_batch_id'],
            }, self.store)
        self.assertEqual(self.store.price_versions(), [])

    def test_rejects_multiple_sheets_formulas_merges_and_hyperlinks(self):
        changes = (
            {'xl/workbook.xml': lambda xml: xml.replace(
                b'</sheets>', b'<sheet name="Second" sheetId="2" r:id="rId2"/></sheets>')},
            {'xl/worksheets/sheet1.xml': lambda xml: xml.replace(
                b'<c r="E2" t="inlineStr">', b'<c r="E2"><f>35+1</f><v>36</v></c><c r="Z2" t="inlineStr">')},
            {'xl/worksheets/sheet1.xml': lambda xml: xml.replace(
                b'</sheetData>', b'</sheetData><mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells>')},
            {'xl/worksheets/sheet1.xml': lambda xml: xml.replace(
                b'</sheetData>', b'</sheetData><hyperlinks><hyperlink ref="A1" r:id="rId2"/></hyperlinks>')},
        )
        for edit in changes:
            with self.subTest(edit=tuple(edit)):
                with self.assertRaises(ValidationError):
                    m10.run(self.stage_payload(self.make_workbook(edit)), self.store)
        self.assertEqual(self.store.price_versions(), [])

    def test_rejects_external_relationships_macros_and_oversized_zip(self):
        external = self.make_workbook({'xl/_rels/workbook.xml.rels': lambda xml: xml.replace(
            b'Target="worksheets/sheet1.xml"',
            b'Target="https://example.invalid/sheet1.xml" TargetMode="External"')})
        macro = self.make_workbook(extra={'xl/vbaProject.bin': b'fake macro'})
        for data in (external, macro):
            with self.subTest(data_len=len(data)), self.assertRaises(ValidationError):
                m10.run(self.stage_payload(data), self.store)

        too_large = BytesIO()
        with ZipFile(too_large, 'w', ZIP_DEFLATED) as archive:
            archive.writestr('padding', b'x' * (m10.MAX_UNCOMPRESSED_BYTES + 1))
        with self.assertRaises(ValidationError):
            m10.run(self.stage_payload(too_large.getvalue()), self.store)

    def test_rejects_bad_names_payload_and_missing_batch_before_approval(self):
        for payload in (
            {'file_name': '../fictional.xlsx', 'file_base64': 'eA=='},
            {'file_name': 'fictional.xlsm', 'file_base64': 'eA=='},
            {'file_name': 'fictional.xlsx', 'file_base64': 'bad!'},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                m10.run({'action': 'stage', **payload}, self.store)

        staged = m10.run(m10.SPEC['defaults'], self.store)
        candidate_id = staged['staged_rows'][0]['record_id']
        with self.assertRaises(ValidationError):
            m10.run({'action': 'approve', 'candidate_ids': [candidate_id], 'confirmed_by': '担当'}, self.store)
        self.assertEqual(self.store.price_versions(), [])


if __name__ == '__main__':
    unittest.main()
