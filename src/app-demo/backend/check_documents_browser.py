"""Use a dedicated empty database. Creates a fictional case/quotes and downloads sample PDFs."""
import os,re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
 page=b.new_page(viewport={'width':1440,'height':1080},accept_downloads=True)
 page.set_default_timeout(5000)
 errors=[]; research=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('request',lambda r:research.append(r.url) if '/price-research' in r.url else None)
 base=os.environ.get('REPAIR_BASE_URL', 'http://127.0.0.1:8019');page.goto(base);page.wait_for_load_state('networkidle')
 page.get_by_role('button',name='＋ 新規案件',exact=True).click()
 page.get_by_label('案件名',exact=True).fill('シビック オイル交換')
 page.get_by_label('宛名（見積書・請求書）',exact=True).fill('山田 太郎様（サンプル）')
 page.get_by_label('電話メモ（内部用）',exact=True).fill('内線確認用の秘密メモ：折り返しは明日の朝。診断後に料金確認。')
 page.get_by_role('button',name='案件を登録',exact=True).click()
 row=page.locator('.case-table tbody tr').first
 expect(row).to_contain_text('山田 太郎様（サンプル）')
 expect(row.locator('.case-document')).to_be_disabled()
 case=page.request.get(base+'/api/cases').json()[0]
 grade=page.request.get(base+'/api/vehicles/FL4').json()['grades'][0]
 quote={'case_id':case['id'],'vehicle_id':'FL4','year':2022,'grade':grade,'items':[{'job_id':'oil','selected_source_ids':['oil-0'],'labor_price':1000,'parts_price':5000,'conditions':'オイル交換のみ。フィルター別。','adjustment_reason':''}]}
 r=page.request.post(base+'/api/estimates',data=quote);assert r.status==201,r.text()
 page.reload();page.wait_for_load_state('networkidle')
 expect(row.locator('.case-phone-preview')).to_contain_text('折り返し')
 row.locator('.case-document').click()
 expect(page.get_by_role('heading',name='見積書・請求書を出力',exact=True)).to_be_visible()
 page.screenshot(path='/tmp/case-documents-desktop.png',full_page=True)
 for button,name in [('見積書PDF','estimate'),('請求書PDF','invoice')]:
  with page.expect_download() as info: page.get_by_role('button',name=button,exact=True).click()
  download=info.value;download.save_as('/tmp/case-'+name+'.pdf')
  data=Path('/tmp/case-'+name+'.pdf').read_bytes()
  assert data.startswith(b'%PDF-1.4') and data.endswith(b'%%EOF\n')
  xref=int(re.search(rb'startxref\n(\d+)',data).group(1));assert data[xref:xref+4]==b'xref'
  for offset in re.findall(rb'(\d{10}) 00000 n ',data):assert re.match(rb'\d+ 0 obj',data[int(offset):])
  assert b'/Count 1 ' in data
  assert '秘密メモ'.encode() not in data
 page.get_by_role('button',name='宛名・電話メモを編集',exact=True).click()
 expect(page.get_by_role('textbox',name='電話メモ（内部用）',exact=True)).to_have_value('内線確認用の秘密メモ：折り返しは明日の朝。診断後に料金確認。')
 page.get_by_label('宛名（見積書・請求書）',exact=True).fill('')
 page.get_by_role('button',name='変更を保存',exact=True).click()
 expect(page.get_by_role('button',name='見積書PDF',exact=True)).to_be_disabled()
 # Long public conditions must create multiple valid pages without internal notes.
 quote['items'][0]['conditions']='長文の作業条件を確認します。\n' * 60
 saved=page.request.post(base+'/api/estimates',data=quote);assert saved.status==201
 fields={k:case[k] for k in ['title','vehicle_label','status','amount','due_date','notes','recipient_name','phone_memo']}
 fields['recipient_name']='サンプル お客様様';page.request.put(base+'/api/cases/'+case['id'],data=fields)
 page.reload();page.wait_for_load_state('networkidle');row.locator('.case-document').click()
 with page.expect_download() as info:page.get_by_role('button',name='見積書PDF',exact=True).click()
 info.value.save_as('/tmp/case-estimate-multipage.pdf')
 data=Path('/tmp/case-estimate-multipage.pdf').read_bytes();count=int(re.search(rb'/Count (\d+)',data).group(1));assert count>1,count
 page.get_by_role('button',name='閉じる',exact=True).click()
 page.get_by_role('button',name='詳細表示',exact=True).click()
 assert row.bounding_box()['height']<60
 expect(row.locator('.case-document')).to_be_visible()
 page.set_viewport_size({'width':390,'height':844})
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 page.get_by_role('button',name='通常表示',exact=True).click();row.locator('.case-edit').click()
 expect(page.get_by_role('textbox',name='電話メモ（内部用）',exact=True)).to_be_visible()
 page.screenshot(path='/tmp/case-documents-mobile.png')
 assert not errors,errors
 assert not research,research
 b.close();print('PASS: recipient/phone memo save+reload, quote linkage, actual PDF downloads, valid xref, multipage, blank recipient, compact actions, mobile, no Gemini or browser errors')
