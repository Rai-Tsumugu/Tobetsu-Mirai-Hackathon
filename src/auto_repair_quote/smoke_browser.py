"""Exercise the integrated UI against a running, isolated demo server."""
import argparse
import json
from pathlib import Path
import re
import tempfile

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8879')
    parser.add_argument('--channel', default='chrome', help='Use chrome, or chromium for Playwright bundled browser')
    args = parser.parse_args()
    artifact_path = Path(tempfile.mkdtemp(prefix='auto-repair-quote-browser-'))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        context = browser.new_context(viewport={'width':1280, 'height':900}, accept_downloads=True)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_default_timeout(60000)
        expect.set_options(timeout=60000)
        page.goto(args.base_url)
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('heading', name='整備見積 統合版')).to_be_visible()
        expect(page.get_by_role('button', name=re.compile(r'2\s*比較'))).to_be_disabled()
        page.get_by_role('button', name='架空: ブレーキ整備', exact=True).click()
        page.get_by_role('button', name='条件を確認して金額を比較').click()
        expect(page.locator('.band-card')).to_have_count(3)
        expect(page.locator('.band-card[aria-pressed="true"]')).to_have_count(0)
        confirm_button = page.get_by_role('button', name='この条件・金額で確定して保存')
        expect(confirm_button).to_be_disabled()
        typical = page.locator('.band-card').filter(has_text='標準条件')
        expect(typical).to_contain_text('14,300')
        typical.click()
        expect(typical).to_have_attribute('aria-pressed','true')
        page.get_by_label('手動の確定額（任意）').fill('15000')
        expect(confirm_button).to_be_disabled()
        page.get_by_label('修正理由（手動変更時）').fill('架空:担当者が説明済みの調整')
        confirm_button.click()
        expect(page.locator('.final-price')).to_contain_text('15,000')
        expect(page.get_by_role('button', name='確定snapshotをJSONで保存')).to_be_visible()
        expect(page.locator('.comparison-card .summary-callout')).to_contain_text('15,000')
        expect(page.locator('.comparison-card .next-action')).to_have_count(0)
        expect(page.locator('.print-sheet')).to_contain_text('手動調整')
        expect(page.locator('.print-sheet')).to_contain_text('税配分は未確認')
        page.get_by_label('電話で伝える条件').fill('架空:追加作業があれば再連絡')
        page.get_by_role('button', name='電話で伝えた内容を記録').click()
        expect(page.get_by_role('status')).to_contain_text('通信台帳に記録')
        with page.expect_download() as download_info:
            page.get_by_role('button', name='確定snapshotをJSONで保存').click()
        download_path = artifact_path/'confirmed.json'
        download_info.value.save_as(download_path)
        saved = json.loads(download_path.read_text())
        assert saved['quote']['final_amount'] == saved['document']['final_amount'] == saved['summary']['amount'] == 15000
        assert saved['communications'][0]['communicated_amount'] == 15000
        page.screenshot(path=str(artifact_path/'confirmed-desktop.png'), full_page=True)
        page.emulate_media(media='print')
        expect(page.locator('.print-sheet')).to_be_visible()
        expect(page.locator('.app-header')).not_to_be_visible()
        expect(page.locator('.input-column')).not_to_be_visible()
        expect(page.locator('.communication-box')).not_to_be_visible()
        page.pdf(path=str(artifact_path/'quote.pdf'), format='A4')
        page.emulate_media(media='screen')

        # Editing a confirmed snapshot opens a new proposal and clears old views.
        page.get_by_label('時間単価（円 / 人時）').fill('9000')
        expect(page.locator('.print-sheet')).to_have_count(0)
        page.get_by_role('button', name='条件を確認して金額を比較').click()
        expect(page.locator('.band-card')).to_have_count(3)
        expect(page.locator('.band-card[aria-pressed="true"]')).to_have_count(0)
        typical = page.locator('.band-card').filter(has_text='標準条件')
        expect(typical).to_contain_text('15,950')
        typical.click()
        confirm_button.click()
        expect(page.locator('.final-price')).to_contain_text('15,950')
        expect(page.locator('.print-sheet')).to_contain_text('版 2')
        page.get_by_label('電話で伝える条件').fill('架空:追加変更の条件を伝達')
        page.get_by_role('button',name='電話で伝えた内容を記録').click()
        expect(page.get_by_role('status')).to_contain_text('通信台帳に記録')
        page.locator('.support-section > summary').click()
        page.get_by_role('button',name='追加変更を未了承で記録').click()
        expect(page.locator('.tool-result')).to_contain_text('"ack_status": "pending"')
        page.get_by_role('button',name='顧客了承を記録').click()
        expect(page.locator('.tool-result')).to_contain_text('"ack_status": "accepted"')
        expect(page.locator('.tool-result')).to_contain_text('"communicated_amount": 15950')
        expect(page.locator('.history-select').filter(has_text=saved['quote']['quote_id'])).to_have_count(2)
        old = page.locator('.history-select').filter(has_text=re.compile(r'版 1 /'))
        old.filter(has_text=saved['quote']['quote_id']).click()
        expect(page.locator('.final-price')).to_contain_text('15,000')
        expect(page.get_by_label('時間単価（円 / 人時）')).to_have_value('8000')

        page.get_by_role('button', name='登録条件で電話概算').click()
        expect(page.locator('.band-card')).to_have_count(3)
        expect(page.locator('.band-card').filter(has_text='標準条件')).to_contain_text('14,300')
        page.locator('.band-card').filter(has_text='低い条件').click()
        expect(confirm_button).to_be_enabled()

        def unavailable_shortcut(route):
            response = route.fetch()
            result = response.json()
            result['shortcut_available'] = False
            result['quote']['status'] = 'blocked'
            for field in ('subtotal','tax','total'):
                result['quote'][field] = {band:None for band in ('low','typical','high')}
            route.fulfill(response=response,json=result)
        page.route('**/api/quotes/quick',unavailable_shortcut)
        page.get_by_role('button',name='登録条件で電話概算').click()
        expect(page.locator('.status-pill').first).to_have_text('確認待ち')
        expect(confirm_button).to_be_disabled()
        expect(page.locator('.band-card:disabled')).to_have_count(3)
        page.unroute('**/api/quotes/quick')

        # A missing human-hour value must block confirmation, never show 0 yen.
        page.get_by_label('標準条件の人時', exact=True).fill('')
        page.get_by_role('button', name='条件を確認して金額を比較').click()
        expect(page.locator('.status-pill').first).to_have_text('確認待ち')
        expect(page.locator('.band-card:disabled')).to_have_count(3)
        expect(confirm_button).to_be_disabled()
        expect(page.locator('.band-card').first).to_contain_text('未確認')

        # Mobile layout and initial request recovery are separate browser states.
        mobile = context.new_page()
        mobile.set_viewport_size({'width':390,'height':844})
        mobile.on('pageerror',lambda error: errors.append(str(error)))
        mobile.goto(args.base_url)
        mobile.wait_for_load_state('networkidle')
        mobile.get_by_role('button',name='条件を確認して金額を比較').click()
        expect(mobile.locator('.band-card')).to_have_count(3)
        assert mobile.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        mobile.screenshot(path=str(artifact_path/'mobile.png'),full_page=True)
        failed = context.new_page()
        failed.route('**/api/demo',lambda route:route.fulfill(status=503,json={'detail':'test outage'}))
        failed.goto(args.base_url)
        expect(failed.get_by_role('button',name='初期データを再読み込み')).to_be_visible()
        failed.unroute('**/api/demo')
        failed.get_by_role('button',name='初期データを再読み込み').click()
        expect(failed.get_by_role('button',name='条件を確認して金額を比較')).to_be_visible()
        assert not errors, errors
        context.close()
        browser.close()
    print(json.dumps({'status':'passed','checks':['selection','manual_amount','communication','json_export','print','revision','change_approval','old_snapshot','quick_quote','quick_registration_gate','missing_input','mobile','request_recovery'], 'artifacts':str(artifact_path)},ensure_ascii=False))


if __name__ == '__main__':
    main()
