import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';
import type { HoursBasis, RateProposal, RateVersion } from './types';

const today = new Date().toISOString().slice(0, 10);
const year_start = `${today.slice(0, 4)}-01-01`;
const year_end = `${today.slice(0, 4)}-12-31`;
type RateHistoryRow = { proposal_id: string; labor_rate: RateVersion['labor_rate']; effective_to: string | null };

export default function R03SalaryMultiplier() {
  const [daily_pay_yen, set_daily_pay_yen] = useState('10000');
  const [paid_days_per_year, set_paid_days_per_year] = useState('240');
  const [approved_multiplier, set_approved_multiplier] = useState('3');
  const [multiplier_approved_by, set_multiplier_approved_by] = useState('');
  const [salary_basis_acknowledged, set_salary_basis_acknowledged] = useState(false);
  const [period_total_person_hours, set_period_total_person_hours] = useState('1600');
  const [u_period, set_u_period] = useState('0.75');
  const [hours_basis, set_hours_basis] = useState<HoursBasis | ''>('total_person_hours');
  const [job_hours, set_job_hours] = useState({ low: '1', typical: '1.5', high: '2.5' });
  const [job_billable_ratio, set_job_billable_ratio] = useState('0.8');
  const [effective_from, set_effective_from] = useState(today);
  const [version, set_version] = useState<RateVersion | null>(null);
  const [history, set_history] = useState<RateHistoryRow[]>([]);
  const [approved_by, set_approved_by] = useState('');
  const [approval_reason, set_approval_reason] = useState('');
  const [error, set_error] = useState('');
  const [busy, set_busy] = useState(false);

  async function refresh_history() {
    try { set_history(await api.list_rates()); } catch { /* Show history when the shared local API is available. */ }
  }
  useEffect(() => { void refresh_history(); }, []);

  async function calculate_rate(event: FormEvent) {
    event.preventDefault(); set_busy(true); set_error(''); set_version(null);
    const numeric = (value: string) => value.trim() === '' ? null : Number(value);
    const proposal: RateProposal = {
      module_id: 'R03', period_start: year_start, period_end: year_end, effective_from,
      allocable_cost_yen: null,
      period_total_person_hours: numeric(period_total_person_hours), u_period: numeric(u_period),
      hours_basis: hours_basis || null,
      job_person_hours: Object.values(job_hours).every(value => value.trim() !== '')
        ? { low: Number(job_hours.low), typical: Number(job_hours.typical), high: Number(job_hours.high) } : null,
      job_billable_ratio: hours_basis === 'total_person_hours' ? numeric(job_billable_ratio) : null,
      costs: [],
      evidence: [], source: 'R03 salary multiplier input',
      notes: '給与倍率は正式原価式と別の比較候補。入力値は工場確認が必要。',
    };
    try {
      const response = await fetch('/api/auto-repair-rate/R03/proposals', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal, daily_pay_yen: numeric(daily_pay_yen),
          paid_days_per_year: numeric(paid_days_per_year), approved_multiplier: numeric(approved_multiplier),
          multiplier_approved_by, salary_basis_acknowledged }),
      });
      if (!response.ok) throw new Error(await response.text() || `API error ${response.status}`);
      set_version(await response.json() as RateVersion);
    } catch (e) { set_error(e instanceof Error ? e.message : '計算に失敗しました'); }
    finally { set_busy(false); }
  }

  async function approve_rate() {
    if (version?.calculation.candidate_yen_per_person_hour == null) return;
    set_busy(true); set_error('');
    try {
      set_version(await api.approve_proposal(version.proposal_id, {
        approved_yen_per_person_hour: version.calculation.candidate_yen_per_person_hour,
        effective_from, approved_by, approval_reason,
      }));
      await refresh_history();
    } catch (e) { set_error(e instanceof Error ? e.message : '承認に失敗しました'); }
    finally { set_busy(false); }
  }

  return <main className="r03-shell">
    <style>{`
      .r03-shell{--ink:#17333a;--muted:#4b6268;--green:#126257;max-width:760px;min-height:100vh;margin:0 auto;padding:24px clamp(18px,5vw,42px) 60px;border-top:9px solid var(--green);background:#f8f8f3;color:var(--ink);font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif}
      .r03-shell *{box-sizing:border-box}.r03-shell header{padding:10px 0 20px;border-bottom:1px solid #c8d4cf}.r03-shell h1{font-size:clamp(28px,7vw,40px);line-height:1.25;margin:8px 0}.r03-shell header p,.r03-copy{line-height:1.7;color:var(--muted)}.r03-eyebrow{font-weight:700;color:var(--green);letter-spacing:.07em;font-size:13px}
      .r03-notice{padding:14px 16px;margin:18px 0;background:#f5ecd7;border-left:5px solid #d2942f;line-height:1.65;font-weight:700}.r03-form{display:grid;gap:15px;margin:22px 0}.r03-shell label{display:grid;gap:7px;font-weight:700;font-size:15px}.r03-shell input,.r03-shell select{width:100%;min-height:49px;border:1px solid #92a8a1;border-radius:4px;padding:10px 12px;background:white;color:var(--ink);font:inherit}.r03-shell input[type=checkbox]{width:24px;min-height:24px;accent-color:var(--green)}.r03-check{display:flex!important;align-items:flex-start;gap:11px!important;line-height:1.55}.r03-shell button{width:100%;min-height:52px;padding:12px 16px;background:var(--green);color:#fff;border:0;border-radius:4px;font:700 16px inherit;cursor:pointer}.r03-shell button:disabled{opacity:.55;cursor:wait}.r03-shell :focus-visible{outline:3px solid #d2942f;outline-offset:3px}
      .r03-formula,.r03-job{padding:14px 16px;background:#e7efeb;border-left:4px solid #588879;line-height:1.7}.r03-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.r03-grid label{font-size:13px}.r03-result{padding:20px 0;border-block:3px solid var(--green);margin-top:26px}.r03-result h2{font-size:24px;color:#14554d}.r03-result li,.r03-history li{line-height:1.8;overflow-wrap:anywhere}.r03-approval{display:grid;gap:14px;border-top:1px dashed #91a49e;margin-top:20px;padding-top:18px}.r03-error{padding:12px;background:#f8e6e3;color:#84281f}.r03-history{border-top:1px solid #c8d4cf;margin-top:30px;padding-top:16px}
      @media(max-width:430px){.r03-shell{padding-top:17px}.r03-grid{grid-template-columns:1fr 1fr}.r03-grid label:last-child{grid-column:1/-1}}@media(prefers-reduced-motion:reduce){.r03-shell *, .r03-shell *::before,.r03-shell *::after{scroll-behavior:auto!important;animation-duration:.01ms!important;transition-duration:.01ms!important}}
    `}</style>
    <header><p className="r03-eyebrow">R03　給与倍率の目安</p><h1>給与をもとに<br />比較候補を試算</h1><p>入力された日給・年間支給日数・工場で設定した倍率を期間請求可能人時で割り、参考候補を計算します。</p></header>
    <aside className="r03-notice">以下のフォームに最初から入っている日給・支給日数・倍率・労働人時・請求割合・案件人時・案件割合は、すべて操作確認用の架空例です。工場の実績や推奨値ではありません。録音に出た「約3倍」は一社の目安発言で、一般相場や実測原価ではありません。候補の適用には設定確認と別途の単価承認が必要です。</aside>
    <form className="r03-form" onSubmit={calculate_rate}>
      <label>日給（円/日・架空例）<input inputMode="numeric" value={daily_pay_yen} onChange={event => set_daily_pay_yen(event.target.value)} placeholder="不明なら空欄" /></label>
      <label>年間の支給日数（日/年・架空例）<input inputMode="numeric" value={paid_days_per_year} onChange={event => set_paid_days_per_year(event.target.value)} placeholder="勤務日数が未確認なら空欄" /></label>
      <label>この工場で設定する給与倍率（架空例）<input inputMode="decimal" value={approved_multiplier} onChange={event => set_approved_multiplier(event.target.value)} placeholder="社長が設定" /></label>
      <label>倍率を確認・設定した社長<input value={multiplier_approved_by} onChange={event => set_multiplier_approved_by(event.target.value)} placeholder="承認者名" /></label>
      <label className="r03-check"><input type="checkbox" checked={salary_basis_acknowledged} onChange={event => set_salary_basis_acknowledged(event.target.checked)} /><span>この方式は給与倍率による比較用目安であり、正式な原価式や他社一般相場を示さないことを確認しました。</span></label>
      <label>期間の総労働人時（架空例）<input inputMode="decimal" value={period_total_person_hours} onChange={event => set_period_total_person_hours(event.target.value)} placeholder="不明なら空欄" /></label>
      <label>期間の請求可能割合 u_period（架空例）<input inputMode="decimal" min="0" max="1" step="0.01" value={u_period} onChange={event => set_u_period(event.target.value)} placeholder="不明なら空欄" /></label>
      <p className="r03-formula"><strong>候補式</strong><br />年間給与換算 = 日給 × 年間支給日数<br />期間請求可能人時 = 期間総労働人時 × u_period<br />候補 = 年間給与換算 × 社長承認済み倍率 ÷ 期間請求可能人時<br />勤務日数や分母が不明または0なら候補を止めて記録します。</p>
      <section className="r03-job"><strong>案件の請求人時は期間分母と別に扱います。</strong><br />総人時基準なら案件請求可能割合を案件人時に一度適用し、請求可能人時入力済みならそのまま表示します。</section>
      <label>案件の時間基準<select value={hours_basis} onChange={event => set_hours_basis(event.target.value as HoursBasis | '')}><option value="">選択してください</option><option value="total_person_hours">総人時から換算</option><option value="billable_person_hours">請求可能人時を入力済み</option></select></label>
      <div className="r03-grid">{(['low', 'typical', 'high'] as const).map(key => <label key={key}>{key === 'low' ? '低' : key === 'typical' ? '標準' : '高'}・案件人時（架空例）<input inputMode="decimal" value={job_hours[key]} onChange={event => set_job_hours({ ...job_hours, [key]: event.target.value })} /></label>)}</div>
      {hours_basis === 'total_person_hours' && <label>案件請求可能割合（架空例・案件だけに適用）<input inputMode="decimal" min="0" max="1" step="0.01" value={job_billable_ratio} onChange={event => set_job_billable_ratio(event.target.value)} /></label>}
      <label>候補の適用開始日<input type="date" value={effective_from} onChange={event => set_effective_from(event.target.value)} required /></label>
      <button disabled={busy}>{busy ? '処理中…' : '候補を試算して保存'}</button>
    </form>
    {error && <p role="alert" className="r03-error">{error}</p>}
    {version && <section className="r03-result" aria-live="polite">
      <h2>{version.calculation.candidate_yen_per_person_hour == null ? '候補を出せません' : `候補 ${Math.round(version.calculation.candidate_yen_per_person_hour).toLocaleString()} 円 / 人時`}</h2>
      <p>状態: {version.status === 'blocked' ? '入力・確認待ち（停止中）' : version.status === 'approved' ? '人が適用承認済み' : '比較候補・未承認'}</p>
      <p>期間: {year_start} 〜 {year_end}　適用開始予定: {effective_from}</p>
      {version.calculation.unknowns.length > 0 && <p>不足・停止理由: {version.calculation.unknowns.join('、')}</p>}
      {version.calculation.job_unknowns.length > 0 && <p>案件人時の不足: {version.calculation.job_unknowns.join('、')}</p>}
      {version.calculation.job_billable_person_hours && <p>案件請求人時（低／標準／高）: {version.calculation.job_billable_person_hours.low} ／ {version.calculation.job_billable_person_hours.typical} ／ {version.calculation.job_billable_person_hours.high} 人時</p>}
      <ul>{version.calculation.basis.map((row, index) => <li key={index}>{row.label}: {String(row.value)} {row.unit}</li>)}</ul>
      {version.calculation.excluded_items.map(item => <p key={item.cost_id}>費用プールから除外: {item.label}（{item.billing_class === 'separately_billed_item' ? '別請求の部品・材料' : item.excluded_reason ?? '対象外'}）</p>)}
      <h3>入力根拠</h3>
      {version.evidence.map((item, index) => <p key={index}>根拠: {item.label}={String(item.value ?? '未入力')} {item.unit} / 状態 {item.status} / 出典 {item.source ?? '未入力'} / 記録 {item.recorded_at} / {item.notes ?? '備考なし'}</p>)}
      {version.labor_rate && <p><strong>承認後に発行された適用単価: {version.labor_rate.yen_per_person_hour.toLocaleString()} 円/人時（{version.labor_rate.effective_from}〜）</strong></p>}
      {version.status === 'draft' && version.calculation.candidate_yen_per_person_hour != null && <div className="r03-approval"><h3>候補単価の社長承認</h3>
        <label>承認者<input value={approved_by} onChange={event => set_approved_by(event.target.value)} required /></label>
        <label>承認理由<input value={approval_reason} onChange={event => set_approval_reason(event.target.value)} required /></label>
        <button type="button" disabled={busy || !approved_by.trim() || !approval_reason.trim()} onClick={approve_rate}>候補を承認して適用履歴に保存</button>
      </div>}
    </section>}
    <section className="r03-history"><h2>承認済み単価の履歴</h2><button type="button" onClick={refresh_history}>履歴を更新</button>{history.length ? <ul>{history.map(item => <li key={item.proposal_id}>{item.labor_rate?.effective_from}〜{item.effective_to ?? '現在'}　{item.labor_rate?.yen_per_person_hour.toLocaleString()} 円/人時</li>)}</ul> : <p className="r03-copy">共有APIに保存された承認済み単価はここに表示します。</p>}</section>
  </main>;
}
