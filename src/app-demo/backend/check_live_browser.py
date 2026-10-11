"""Mocked Google responses + real FastAPI/SQLite/browser. Never sends Google requests."""
import json
import os
import sys
from pathlib import Path

PORT = 8019


def serve_fixture():
    import app
    import uvicorn
    import gemini
    urls = ['https://example.org/test/brake', 'https://example.org/test/unknown-tax', 'https://example.org/test/other-car']
    os.environ['GEMINI_API_KEY'] = 'mock-only-not-a-real-key'
    app.DB_PATH = Path(os.environ['REPAIR_DB_PATH'])
    gemini.reserve_request = lambda: None
    def fake_generate(prompt, *, tools=None, schema=None):
        if tools:
            return {'groundingMetadata': {'groundingChunks': [{'web': {'uri': u, 'title': '検証用記事 ' + str(i)}} for i, u in enumerate(urls)], 'searchEntryPoint': {'renderedContent': '<p>モック検証用の検索候補</p>'}}}, 'モックのWeb調査結果'
        sources = []
        for i, url in enumerate(urls):
            sources.append(dict(job_id='brake', source_url=url, labor_price=6600, parts_price=None, total_price=None, tax_included=True if i != 1 else None, tax_rate=0.1, vehicle_match='exact' if i != 2 else 'similar', work_matches=True, work_conditions='前輪左右・パッド持込なし', published_at=None, evidence='工賃6,600円（税込）' if i != 1 else '工賃6,600円・税区分不明'))
        data = {'sources': sources}
        return {}, json.dumps(data, ensure_ascii=False)
    gemini.generate = fake_generate
    uvicorn.run(app.app, host='127.0.0.1', port=PORT)


def check():
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        page = browser.new_page(viewport={'width': 1440, 'height': 1080})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(f'http://127.0.0.1:{PORT}')
        page.wait_for_load_state('networkidle')
        outbound = []
        page.on('request', lambda request: outbound.append(request.url) if '/api/price-research' in request.url or '/api/vehicle-research' in request.url else None)
        form = page.locator('.manual-form')
        for label, value in [('メーカー', '検証用メーカー'), ('車種名', '検証用車両'), ('型式', 'TEST'), ('年式', '2023'), ('グレード・仕様', '検証用仕様')]:
            form.get_by_label(label, exact=True).fill(value)
        page.get_by_role('button', name='この車両を暫定登録', exact=True).click()
        expect(page.get_by_label('年式', exact=True)).to_have_value('2023')
        expect(page.get_by_label('グレード・仕様', exact=True)).to_have_value('検証用仕様')
        assert not outbound, outbound
        expect(page.get_by_role('button', name='Webで車両情報を調べる', exact=True)).to_have_count(0)
        page.get_by_role('button', name='作業を選ぶ', exact=True).click()
        page.get_by_role('button', name='AIで工賃を調査（Gemini）', exact=True).click()
        page.get_by_label('フロントブレーキパッド交換').check()
        page.get_by_label('融雪剤を使う道路での走行').check()
        page.get_by_label('サビ・ボルトの固着を現車で確認').check()
        page.screenshot(path='/tmp/repair-winter-conditions.png', full_page=True)
        page.get_by_role('button', name='参考価格を比較する', exact=True).click()
        expect(page.locator('.source-card')).to_have_count(3)
        assert len(outbound) == 1 and '/api/price-research' in outbound[0], outbound
        expect(page.locator('.editor .winter-summary')).to_contain_text('融雪剤')
        expect(page.locator('.median-strip strong')).to_have_text('算出不可')
        expect(page.locator('.source-card').nth(1).get_by_role('checkbox')).to_be_disabled()
        expect(page.locator('.source-card').nth(1)).to_contain_text('税区分不明')
        expect(page.locator('.source-card').nth(2).get_by_role('checkbox')).to_be_disabled()
        page.locator('.source-card').nth(0).get_by_role('checkbox').check()
        expect(page.locator('.median-strip strong')).to_have_text('￥6,000')
        expect(page.get_by_role('link', name='出典ページを確認')).to_have_count(3)
        page.screenshot(path='/tmp/repair-gemini-mock-desktop.png', full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_timeout(300)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path='/tmp/repair-gemini-mock-mobile.png', full_page=True)
        page.get_by_role('button', name='金額を確認する', exact=True).click()
        page.get_by_label('フロントブレーキパッド交換の部品代').fill('12000')
        page.get_by_role('button', name='金額を確定して保存', exact=True).click()
        expect(page.get_by_role('heading', name='見積もりを保存しました')).to_be_visible()
        page.reload()
        page.get_by_role('button', name='保存した見積もり', exact=True).click()
        page.get_by_label('見積もり履歴を検索').fill('TEST')
        page.locator('.history-list > button').first.click()
        expect(page.locator('.detail-total strong')).to_have_text('￥19,800')
        expect(page.locator('.history-detail')).to_contain_text('Gemini Web調査')
        expect(page.locator('.history-detail .winter-summary')).to_contain_text('サビ・ボルトの固着')
        page.locator('.history-item summary').click()
        expect(page.get_by_role('link', name='出典ページ', exact=True)).to_have_count(3)
        page.get_by_role('button', name='この条件で見積もりを作る', exact=True).click()
        expect(page.get_by_label('フロントブレーキパッド交換の確定工賃')).to_have_value('6000')
        expect(page.locator('.winter-summary').first).to_contain_text('融雪剤')
        expect(page.get_by_role('button', name='金額を確定して保存', exact=True)).to_be_enabled()
        assert not errors, errors
        browser.close()
        print('PASS: manual vehicle without AI calls, winter context, mocked labor search, attribution, exclusions, adoption, save/reload/reuse, mobile, no browser errors')


if __name__ == '__main__':
    if '--mock-server' in sys.argv:
        serve_fixture()
    else:
        check()
