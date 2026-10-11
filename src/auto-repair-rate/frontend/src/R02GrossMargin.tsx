import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';
import type { HoursBasis, RateProposal, RateVersion } from './types';

const today = new Date().toISOString().slice(0, 10);
const year_start = `${today.slice(0, 4)}-01-01`;

export default function R02GrossMargin() {
  const [cost_yen, set_cost_yen] = useState('7200000');
  const [period_hours, set_period_hours] = useState('1600');
  const [u_period, set_u_period] = useState('0.75');
  const [gross_margin, set_gross_margin] = useState('0.2');
  const [payroll_nonduplicated, set_payroll_nonduplicated] = useState(false);
  const [materials_yen, set_materials_yen] = useState('300000');
  const [hours_basis, set_hours_basis] = useState<HoursBasis | ''>('total_person_hours');
  const [job_hours, set_job_hours] = useState({ low: '1', typical: '1.5', high: '2.5' });
  const [job_billable_ratio, set_job_billable_ratio] = useState('0.8');
  const [effective_from, set_effective_from] = useState(today);
  const [version, set_version] = useState<RateVersion | null>(null);
  const [history, set_history] = useState<Array<{ proposal_id: string; labor_rate: RateVersion['labor_rate']; effective_to: string | null }>>([]);
  const [approved_by, set_approved_by] = useState('');
  const [approval_reason, set_approval_reason] = useState('');
  const [error, set_error] = useState('');
  const [busy, set_busy] = useState(false);

  async function refresh_history() {
    try { set_history(await api.list_rates()); } catch { /* History remains available from the shared API when it starts. */ }
  }

  async function calculate_rate(event: FormEvent) {
    event.preventDefault(); set_busy(true); set_error(''); set_version(null);
    const numeric = (value: string) => value.trim() === '' ? null : Number(value);
    const proposal: RateProposal = {
      module_id: 'R02', period_start: year_start, period_end: `${today.slice(0, 4)}-12-31`, effective_from,
      allocable_cost_yen: numeric(cost_yen), period_total_person_hours: numeric(period_hours), u_period: numeric(u_period),
      hours_basis: hours_basis || null,
      job_person_hours: Object.values(job_hours).every(value => value.trim() !== '')
        ? { low: Number(job_hours.low), typical: Number(job_hours.typical), high: Number(job_hours.high) } : null,
      job_billable_ratio: hours_basis === 'total_person_hours' ? numeric(job_billable_ratio) : null,
      costs: [
        { cost_id: 'fictional_labor_pool', label: '架空の配賦労務費', amount_yen: numeric(cost_yen), period: year_start,
          source: 'R02 simulator input', evidence_status: 'assumed', billing_class: 'labor_pool', included_in_labor_pool: true, excluded_reason: null },
        ...(numeric(materials_yen) === null ? [] : [{ cost_id: 'fictional_materials', label: '別請求の部品・材料', amount_yen: numeric(materials_yen), period: year_start,
          source: 'R02 simulator input', evidence_status: 'assumed' as const, billing_class: 'separately_billed_item' as const, included_in_labor_pool: false, excluded_reason: '別請求のため除外' }]),
      ],
      evidence: [{ label: '配賦費用の入力', value: numeric(cost_yen), unit: '円/期間', status: 'assumed', source: 'R02 simulator input', evidence_ref: null,
        recorded_at: new Date().toISOString(), notes: '架空デモ入力。実工場の実績ではありません。' }],
      source: 'fictional_simulator', notes: '架空デモ値。実測値・相場ではありません。',
    };
    try {
      const response = await fetch('/api/auto-repair-rate/R02/proposals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ proposal, gross_margin: numeric(gross_margin), payroll_nonduplicated }) });
      if (!response.ok) throw new Error(await response.text() || `API error ${response.status}`);
      set_version(await response.json() as RateVersion);
    } catch (e) { set_error(e instanceof Error ? e.message : '計算に失敗しました'); }
    finally { set_busy(false); }
  }

  async function approve_rate() {
    if (!version?.calculation.candidate_yen_per_person_hour) return;
    set_busy(true); set_error('');
    try {
      set_version(await api.approve_proposal(version.proposal_id, {
        approved_yen_per_person_hour: version.calculation.candidate_yen_per_person_hour, effective_from, approved_by, approval_reason,
      }));
      await refresh_history();
    } catch (e) { set_error(e instanceof Error ? e.message : '承認に失敗しました'); }
    finally { set_busy(false); }
  }

  return <main className="r02-shell">
    <style>{`
      .r02-shell{--ink:#17333a;--muted:#4b6268;--green:#126257;max-width:760px;min-height:100vh;margin:0 auto;padding:24px clamp(18px,5vw,42px) 60px;border-top:9px solid var(--green);background:#f8f8f3;color:var(--ink);font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif}
      .r02-shell *{box-sizing:border-box}.r02-shell header{padding:10px 0 20px;border-bottom:1px solid #c8d4cf}.r02-shell h1{font-size:clamp(28px,7vw,40px);line-height:1.25;margin:8px 0}.r02-shell header p:last-child,.r02-shell .copy{line-height:1.7;color:var(--muted)}.r02-eyebrow{font-weight:700;color:var(--green);letter-spacing:.07em;font-size:13px}
      .r02-fictional{padding:14px 16px;margin:18px 0;background:#f5ecd7;border-left:5px solid #d2942f;line-height:1.6;font-weight:700}.r02-form{display:grid;gap:15px;margin:22px 0}.r02-shell label{display:grid;gap:7px;font-weight:700;font-size:15px}.r02-shell input,.r02-shell select{width:100%;min-height:49px;border:1px solid #92a8a1;border-radius:4px;padding:10px 12px;background:white;color:var(--ink);font:inherit}.r02-shell button{width:100%;min-height:52px;padding:12px 16px;background:var(--green);color:#fff;border:0;border-radius:4px;font:700 16px inherit;cursor:pointer}.r02-shell button:disabled{opacity:.55;cursor:wait}.r02-shell :focus-visible{outline:3px solid #d2942f;outline-offset:3px}
      .r02-formula,.r02-job{padding:14px 16px;background:#e7efeb;border-left:4px solid #588879;line-height:1.65}.r02-job-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.r02-job-grid label{font-size:13px}.r02-result{padding:20px 0;border-block:3px solid var(--green);margin-top:26px}.r02-result h2{font-size:24px;color:#14554d}.r02-result li{line-height:1.8}.r02-approval{display:grid;gap:14px;border-top:1px dashed #91a49e;margin-top:20px;padding-top:18px}.r02-error{padding:12px;background:#f8e6e3;color:#84281f}.r02-history{border-top:1px solid #c8d4cf;margin-top:30px;padding-top:16px}.r02-history li{overflow-wrap:anywhere;line-height:1.7}
      @media(max-width:430px){.r02-shell{padding-top:17px}.r02-job-grid{grid-template-columns:1fr 1fr}.r02-job-grid label:last-child{grid-column:1/-1}}@media(prefers-reduced-motion:reduce){.r02-shell *, .r02-shell *::before,.r02-shell *::after{scroll-behavior:auto!important;animation-duration:.01ms!important;transition-duration:.01ms!important}}
    `}</style>
    <header><p className="r02-eyebrow">R02　粗利率から逆算</p><h1>粗利を含む<br />時間単価を考える</h1><p>期間の原価を請求可能人時で割り、売上高に対する粗利率から候補を計算します。適用には人の承認が必要です。</p></header>
    <aside className="r02-fictional">架空デモ値です。実測値や地域相場ではありません。</aside>
    <form className="r02-form" onSubmit={calculate_rate}>
      <label>期間の配賦原価（円）<input inputMode="numeric" value={cost_yen} onChange={event => set_cost_yen(event.target.value)} placeholder="根拠が不明なら空欄" /></label>
      <label>期間の総労働人時<input inputMode="decimal" value={period_hours} onChange={event => set_period_hours(event.target.value)} placeholder="不明なら空欄" /></label>
      <label>期間の請求可能割合 u_period<input inputMode="decimal" min="0" max="1" step="0.01" value={u_period} onChange={event => set_u_period(event.target.value)} placeholder="不明なら空欄" /></label>
      <label>粗利率 m<input inputMode="decimal" min="0" max="0.99" step="0.01" value={gross_margin} onChange={event => set_gross_margin(event.target.value)} required /></label>
      <p className="r02-formula"><strong>計算の考え方</strong><br />粗利率 = 粗利益 ÷ 売上高。原価に上乗せする率とは異なります。<br />c = 配賦原価 ÷ (期間総労働人時 × u_period)<br />候補単価 = c ÷ (1 − m)</p>
      <label>別請求の部品・材料費（円）<input inputMode="numeric" value={materials_yen} onChange={event => set_materials_yen(event.target.value)} /></label>
      <p className="copy">別請求の費用は労務原価から除外して記録します。入力した配賦原価と含めた費目の合計も照合します。</p>
      <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}><input type="checkbox" checked={payroll_nonduplicated} onChange={event => set_payroll_nonduplicated(event.target.checked)} style={{ width: 22, minHeight: 22, marginTop: 2 }} />給与・賞与などの人件費が配賦原価に重複計上されていないことを確認しました。</label>
      <section className="r02-job"><strong>案件時間は期間単価と別に計算</strong><br />案件の時間基準が未選択なら、案件の請求人時は出しません。</section>
      <label>案件の時間基準<select value={hours_basis} onChange={event => set_hours_basis(event.target.value as HoursBasis | '')}><option value="">選択してください</option><option value="total_person_hours">総人時から換算</option><option value="billable_person_hours">請求可能人時を入力済み</option></select></label>
      <div className="r02-job-grid">{(['low', 'typical', 'high'] as const).map(key => <label key={key}>{key === 'low' ? '低' : key === 'typical' ? '標準' : '高'}・案件人時<input inputMode="decimal" value={job_hours[key]} onChange={event => set_job_hours({ ...job_hours, [key]: event.target.value })} /></label>)}</div>
      {hours_basis === 'total_person_hours' && <label>案件請求可能割合（案件だけに適用）<input inputMode="decimal" min="0" max="1" step="0.01" value={job_billable_ratio} onChange={event => set_job_billable_ratio(event.target.value)} /></label>}
      <label>候補の適用開始日<input type="date" value={effective_from} onChange={event => set_effective_from(event.target.value)} required /></label>
      <button disabled={busy}>{busy ? '処理中…' : '候補を計算して保存'}</button>
    </form>
    {error && <p role="alert" className="r02-error">{error}</p>}
    {version && <section className="r02-result" aria-live="polite">
      <h2>{version.calculation.candidate_yen_per_person_hour == null ? '候補を出せません' : `候補 ${Math.round(version.calculation.candidate_yen_per_person_hour).toLocaleString()} 円 / 人時`}</h2>
      <p>状態: {version.status === 'blocked' ? '根拠・入力の確認待ち' : version.status === 'approved' ? '人が承認済み' : '未承認の候補'}</p>
      <p>期間: {year_start} 〜 {`${today.slice(0, 4)}-12-31`}　適用開始予定: {effective_from}</p>
      {version.calculation.unknowns.length > 0 && <p>不足・停止理由: {version.calculation.unknowns.join('、')}</p>}
      {version.calculation.job_unknowns.length > 0 && <p>案件時間の不足: {version.calculation.job_unknowns.join('、')}</p>}
      {version.calculation.job_billable_person_hours && <p>案件請求人時（低／標準／高）: {version.calculation.job_billable_person_hours.low} ／ {version.calculation.job_billable_person_hours.typical} ／ {version.calculation.job_billable_person_hours.high} 人時</p>}
      {version.calculation.excluded_items.map(item => <p key={item.cost_id}>除外記録: {item.label}（別請求の部品・材料）</p>)}
      <ul>{version.calculation.basis.map((row, index) => <li key={index}>{row.label}: {String(row.value)} {row.unit}</li>)}</ul>
      <p>根拠状態: {version.evidence.map(item => `${item.label}（${item.status}・${item.source ?? '出典未入力'}）`).join('、')}</p>
      {version.labor_rate && <p><strong>承認後の単価: {version.labor_rate.yen_per_person_hour.toLocaleString()} 円/人時（{version.labor_rate.effective_from}〜）</strong></p>}
      {version.status === 'draft' && version.calculation.candidate_yen_per_person_hour != null && <div className="r02-approval"><h3>人による承認</h3>
        <label>承認者<input value={approved_by} onChange={event => set_approved_by(event.target.value)} required /></label>
        <label>承認理由<input value={approval_reason} onChange={event => set_approval_reason(event.target.value)} required /></label>
        <button type="button" disabled={busy || !approved_by.trim() || !approval_reason.trim()} onClick={approve_rate}>この候補を承認して履歴に保存</button>
      </div>}
    </section>}
    <section className="r02-history"><h2>承認済み単価の履歴</h2><button type="button" onClick={refresh_history}>履歴を更新</button>{history.length ? <ul>{history.map(item => <li key={item.proposal_id}>{item.labor_rate?.effective_from}〜{item.effective_to ?? '現在'}　{item.labor_rate?.yen_per_person_hour.toLocaleString()} 円/人時</li>)}</ul> : <p className="copy">共有APIに保存された承認済み履歴を表示します。</p>}</section>
  </main>;
}
