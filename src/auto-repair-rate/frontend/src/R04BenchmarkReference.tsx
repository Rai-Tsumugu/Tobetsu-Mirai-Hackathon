import { useState } from 'react';
import type { FormEvent } from 'react';
import type { RateVersion } from './types';

const today = new Date().toISOString().slice(0, 10);

export default function R04BenchmarkReference() {
  const [amount, set_amount] = useState('18000');
  const [currency, set_currency] = useState('JPY');
  const [amount_type, set_amount_type] = useState('labor_only');
  const [hours_basis, set_hours_basis] = useState('documented_person_hours');
  const [hours, set_hours] = useState('3');
  const [conditions, set_conditions] = useState('架空例: 作業範囲や税区分を確認してください');
  const [source_url, set_source_url] = useState('https://example.invalid/fictional-reference');
  const [source_text, set_source_text] = useState('架空の比較資料（実在情報ではありません）');
  const [retrieved_at, set_retrieved_at] = useState(today);
  const [permission_status, set_permission_status] = useState('unknown');
  const [effective_from, set_effective_from] = useState(today);
  const [job_hours_basis, set_job_hours_basis] = useState('');
  const [job_billable_ratio, set_job_billable_ratio] = useState('');
  const [version, set_version] = useState<RateVersion | null>(null);
  const [history, set_history] = useState<Array<{ proposal_id: string; labor_rate: RateVersion['labor_rate']; effective_to: string | null }>>([]);
  const [error, set_error] = useState('');
  const [busy, set_busy] = useState(false);

  async function refresh_history() {
    try { set_history(await (await fetch('/api/auto-repair-rate/labor-rates')).json()); }
    catch { set_error('承認済み単価の履歴を読み込めませんでした'); }
  }

  async function save_reference(event: FormEvent) {
    event.preventDefault(); set_busy(true); set_error(''); set_version(null);
    const numeric = (value: string) => value.trim() === '' ? null : Number(value);
    try {
      const response = await fetch('/api/auto-repair-rate/R04/proposals', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          period_start: `${today.slice(0, 4)}-01-01`, effective_from,
          amount: numeric(amount), currency, amount_type, hours_basis,
          documented_person_hours: numeric(hours), conditions, source_url: source_url || null,
          source_text, retrieved_at, permission_status, job_hours_basis: job_hours_basis || null,
          job_billable_ratio: job_hours_basis === 'total_person_hours' ? numeric(job_billable_ratio) : null,
        }),
      });
      if (!response.ok) throw new Error(await response.text() || `API error ${response.status}`);
      set_version(await response.json() as RateVersion);
    } catch (e) { set_error(e instanceof Error ? e.message : '資料を保存できませんでした'); }
    finally { set_busy(false); }
  }

  return <main className="r04-shell">
    <style>{`
      .r04-shell{--ink:#24343a;--muted:#53656b;--blue:#285f73;max-width:760px;min-height:100vh;margin:0 auto;padding:24px clamp(18px,5vw,42px) 60px;border-top:9px solid var(--blue);background:#f5f7f6;color:var(--ink);font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif}
      .r04-shell *{box-sizing:border-box}.r04-shell header{padding:10px 0 20px;border-bottom:1px solid #c9d3d4}.r04-shell h1{font-size:clamp(27px,7vw,39px);line-height:1.25;margin:8px 0}.r04-shell header p:last-child,.r04-copy{line-height:1.7;color:var(--muted)}.r04-kicker{font-size:13px;font-weight:700;color:var(--blue)}
      .r04-alert{margin:18px 0;padding:15px 16px;background:#f3ead5;border-left:5px solid #b07b23;line-height:1.65;font-weight:700}.r04-form{display:grid;gap:15px;margin:22px 0}.r04-shell label{display:grid;gap:7px;font-size:15px;font-weight:700}.r04-shell input,.r04-shell select,.r04-shell textarea{width:100%;min-height:49px;border:1px solid #98a9ac;border-radius:4px;padding:10px 12px;background:white;color:var(--ink);font:inherit}.r04-shell textarea{min-height:84px;resize:vertical}.r04-shell button{width:100%;min-height:52px;border:0;border-radius:4px;padding:12px 16px;background:var(--blue);color:white;font:700 16px inherit}.r04-shell button:disabled{opacity:.55}.r04-shell :focus-visible{outline:3px solid #bd872f;outline-offset:3px}.r04-evidence{padding:14px 16px;background:#e6eef0;border-left:4px solid #6b929e;line-height:1.65}.r04-result{margin-top:26px;padding:18px 0;border-block:3px solid var(--blue)}.r04-result h2{font-size:24px}.r04-result li{line-height:1.8;overflow-wrap:anywhere}.r04-error{padding:12px;background:#f8e6e3;color:#84281f}.r04-history{margin-top:30px;border-top:1px solid #c9d3d4;padding-top:18px}.r04-history li{line-height:1.75}
      @media(max-width:430px){.r04-shell{padding-top:17px}}@media(prefers-reduced-motion:reduce){.r04-shell *,.r04-shell *::before,.r04-shell *::after{scroll-behavior:auto!important;animation-duration:.01ms!important;transition-duration:.01ms!important}}
    `}</style>
    <header><p className="r04-kicker">R04　出典付きの比較資料</p><h1>外部の金額を<br />参考として記録する</h1><p>資料を手入力して、条件がそろう場合だけ円/人時に換算します。自工場の単価とは別の記録です。</p></header>
    <aside className="r04-alert">フォームに最初から入っている金額18,000円・対象人時3時間・URL・資料名・条件文は、すべて操作確認用の架空例です。実在の価格や出典ではありません。比較資料は自工場の候補単価にならず、中央値も自動適用しません。許諾・利用条件は自分で確認してください。</aside>
    <form className="r04-form" onSubmit={save_reference}>
      <label>資料の金額（架空例）<input inputMode="decimal" value={amount} onChange={event => set_amount(event.target.value)} required /></label>
      <label>通貨<select value={currency} onChange={event => set_currency(event.target.value)}><option value="JPY">円（JPY）</option><option value="USD">米ドル（USD）</option></select></label>
      <label>金額の範囲<select value={amount_type} onChange={event => set_amount_type(event.target.value)}><option value="labor_only">労務のみ</option><option value="total">部品などを含む総額</option><option value="unknown">範囲が不明</option></select></label>
      <label>人時の根拠<select value={hours_basis} onChange={event => set_hours_basis(event.target.value)}><option value="documented_person_hours">資料に対象作業人時が明記</option><option value="unknown">不明・資料に記載なし</option></select></label>
      <label>資料に記載された対象人時（架空例）<input inputMode="decimal" value={hours} onChange={event => set_hours(event.target.value)} placeholder="不明なら空欄" /></label>
      <label>出典URL（架空例・取得はしません）<input type="url" value={source_url} onChange={event => set_source_url(event.target.value)} placeholder="https://…" /></label>
      <label>資料名・内容（架空例）<textarea value={source_text} onChange={event => set_source_text(event.target.value)} required /></label>
      <label>確認した日<input type="date" value={retrieved_at} onChange={event => set_retrieved_at(event.target.value)} required /></label>
      <label>掲載・利用条件<select value={permission_status} onChange={event => set_permission_status(event.target.value)}><option value="unknown">未確認</option><option value="verified">確認済み</option></select></label>
      <label>比較条件（架空例・作業範囲・地域・税など）<textarea value={conditions} onChange={event => set_conditions(event.target.value)} required /></label>
      <section className="r04-evidence"><strong>案件時間は別の基準で扱う</strong><br />案件の人時基準を選んだ場合だけ、総人時に対する案件比率を記録します。期間の u_period には適用しません。</section>
      <label>案件人時基準<select value={job_hours_basis} onChange={event => set_job_hours_basis(event.target.value)}><option value="">未選択</option><option value="total_person_hours">案件の総人時</option><option value="billable_person_hours">請求可能人時</option></select></label>
      {job_hours_basis === 'total_person_hours' && <label>案件請求可能割合<input inputMode="decimal" min="0" max="1" step="0.01" value={job_billable_ratio} onChange={event => set_job_billable_ratio(event.target.value)} placeholder="未確認なら空欄" /></label>}
      <label>記録上の適用開始日<input type="date" value={effective_from} onChange={event => set_effective_from(event.target.value)} required /></label>
      <button disabled={busy}>{busy ? '保存中…' : '比較資料を保存'}</button>
    </form>
    {error && <p className="r04-error" role="alert">{error}</p>}
    {version && <section className="r04-result" aria-live="polite">
      <h2>{version.calculation.basis.find(row => row.label === '外部比較値')?.value == null ? '参考不可' : `資料上の参考値 ${Number(version.calculation.basis.find(row => row.label === '外部比較値')?.value).toLocaleString()} 円/人時`}</h2>
      <p>この数値は比較資料の記録です。工場単価として使用・承認されていません。</p>
      <p>記録上の適用開始日: {version.calculation.basis.find(row => row.label === '記録上の適用開始日')?.value ?? '未記録'}</p>
      {version.calculation.unknowns.map(item => <p key={item}>{item}</p>)}
      <ul>{version.calculation.basis.map((row, index) => <li key={index}>{row.label}: {String(row.value ?? '未確認')} {row.unit}</li>)}</ul>
      {version.evidence.map((item, index) => <p key={index} className="r04-copy">根拠: {item.label} / {item.source ?? '出典名なし'} / {item.status}</p>)}
      {source_url && <p><a href={source_url} target="_blank" rel="noreferrer">入力した出典を開く</a></p>}
    </section>}
    <section className="r04-history"><h2>自工場で承認済みの単価履歴</h2><button type="button" onClick={refresh_history}>履歴を更新</button>{history.length ? <ul>{history.map(item => <li key={item.proposal_id}>{item.labor_rate?.effective_from}〜{item.effective_to ?? '現在'}　{item.labor_rate?.yen_per_person_hour.toLocaleString()} 円/人時</li>)}</ul> : <p className="r04-copy">この比較画面では自工場単価を変更しません。共有APIの承認済み履歴を表示します。</p>}</section>
  </main>;
}
