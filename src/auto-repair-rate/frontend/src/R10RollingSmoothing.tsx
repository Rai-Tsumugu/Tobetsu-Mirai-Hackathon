import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';
import type { RateVersion } from './types';

const today = new Date();
const months = Array.from({ length: 12 }, (_, i) => { const date = new Date(today.getFullYear(), today.getMonth() - 11 + i, 1); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`; });
type Preview = { available: boolean; blockers: string[]; raw_invoice_month_rate: number | null; smoothed_rate: number | null; total_allocable_cost_yen: number | null; total_billable_hours: number | null; formula: string };

export default function R10RollingSmoothing() {
  const [costs, set_costs] = useState<string[]>(Array(12).fill('100000'));
  const [hours, set_hours] = useState<string[]>(Array(12).fill('100'));
  const [ratios, set_ratios] = useState<string[]>(Array(12).fill('0.75'));
  const [invoice_month, set_invoice_month] = useState('12');
  const [seasonal_applied, set_seasonal_applied] = useState(false);
  const [materials, set_materials] = useState('');
  const [source, set_source] = useState('架空シミュレータ');
  const [source_date, set_source_date] = useState(today.toISOString().slice(0, 10));
  const [evidence_ref, set_evidence_ref] = useState('架空例 R10-2026-01');
  const [evidence_notes, set_evidence_notes] = useState('説明用の直近12か月分の費用・請求人時です。');
  const [preview, set_preview] = useState<Preview | null>(null);
  const [version, set_version] = useState<RateVersion | null>(null);
  const [approved_by, set_approved_by] = useState('');
  const [approval_reason, set_approval_reason] = useState('');
  const [error, set_error] = useState('');
  const [busy, set_busy] = useState(false);
  const change = (setter: typeof set_costs, values: string[], index: number, value: string) => { const next = [...values]; next[index] = value; setter(next); };
  const payload = () => ({ period_start: `${months[0]}-01`, period_end: new Date(Number(months[11].slice(0, 4)), Number(months[11].slice(5, 7)), 0).toISOString().slice(0, 10),
    invoice_month: Number(invoice_month), source_date, effective_from: today.toISOString().slice(0, 10),
    monthly_cost_yen: costs.map(v => v.trim() === '' ? null : Number(v)),
    monthly_total_person_hours: hours.map(v => v.trim() === '' ? null : Number(v)),
    monthly_u_period: ratios.map(v => v.trim() === '' ? null : Number(v)), seasonal_allocation_already_applied: seasonal_applied,
    materials_yen: materials === '' ? null : Number(materials), source, evidence_ref, evidence_notes });
  async function calculate(event: FormEvent) { event.preventDefault(); set_busy(true); set_error(''); set_version(null); try { const response = await fetch('/api/auto-repair-rate/R10/rates/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) }); if (!response.ok) throw new Error(await response.text()); set_preview(await response.json()); } catch (e) { set_error(e instanceof Error ? e.message : '比較に失敗しました'); } finally { set_busy(false); } }
  async function save() { set_busy(true); set_error(''); try { const response = await fetch('/api/auto-repair-rate/R10/proposals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) }); if (!response.ok) throw new Error(await response.text()); set_version(await response.json()); } catch (e) { set_error(e instanceof Error ? e.message : '保存に失敗しました'); } finally { set_busy(false); } }
  async function approve() { if (!version?.calculation.candidate_yen_per_person_hour) return; set_busy(true); try { set_version(await api.approve_proposal(version.proposal_id, { approved_yen_per_person_hour: version.calculation.candidate_yen_per_person_hour, effective_from: today.toISOString().slice(0, 10), approved_by, approval_reason })); } catch (e) { set_error(e instanceof Error ? e.message : '承認に失敗しました'); } finally { set_busy(false); } }
  return <main className="app-shell r10-screen"><style>{`.r10-screen .month-row{display:grid;grid-template-columns:70px repeat(3,minmax(0,1fr));gap:8px;align-items:end;padding:10px 0;border-bottom:1px solid #d5dfdb}.r10-screen .month-row strong{font-size:14px}.r10-screen .month-row label{font-size:12px;min-width:0}.r10-screen .month-row input{min-width:0;padding:8px 6px}.r10-screen .rate-compare{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.r10-screen .rate-box{padding:15px;background:#fff;border:1px solid #c7d3cf;border-radius:7px}.r10-screen output{display:block;font-size:24px;font-weight:800;color:#17665e;margin-top:8px}@media(max-width:480px){.r10-screen .month-row{grid-template-columns:58px repeat(3,minmax(0,1fr));gap:5px}.r10-screen .month-row input{font-size:13px;padding:7px 3px}.r10-screen .rate-compare{grid-template-columns:1fr}}`}</style>
    <header><p className="eyebrow">R10　月次費用平準化</p><h1>12か月の実績で<br />費用変動をならす</h1><p>請求月の生単価と12か月合計費用 ÷ 12か月合計請求可能人時を並べます。</p></header>
    <aside className="fictional">架空の初期値です。実請求・勤怠記録ではありません。不明な月は空欄にすると算定を停止します。</aside>
    <form onSubmit={calculate}>
      <h2>直近12か月の根拠データ</h2>
      <p className="hint">月ごとに費用、総労働人時、u_periodを入力します。平準化単価は月単価の平均ではなく、費用合計 ÷ 請求可能人時合計です。</p>
      {months.map((month, index) => <div className="month-row" key={month}><strong>{month}</strong>
        <label>費用 円<input inputMode="numeric" aria-label={`${month} 費用円`} value={costs[index]} onChange={e => change(set_costs, costs, index, e.target.value)} /></label>
        <label>総人時<input inputMode="decimal" aria-label={`${month} 総労働人時`} value={hours[index]} onChange={e => change(set_hours, hours, index, e.target.value)} /></label>
        <label>u_period<input inputMode="decimal" aria-label={`${month} u_period`} value={ratios[index]} onChange={e => change(set_ratios, ratios, index, e.target.value)} /></label>
      </div>)}
      <label>比較する請求月<select value={invoice_month} onChange={e => set_invoice_month(e.target.value)}>{months.map((month, i) => <option key={month} value={i + 1}>{month}（{i + 1}月）</option>)}</select></label>
      <label className="hint"><span><input type="checkbox" checked={seasonal_applied} onChange={e => set_seasonal_applied(e.target.checked)} style={{ width: 22, minHeight: 22, verticalAlign: 'middle', marginRight: 8 }} />入力済み費用は別の季節配賦を適用済み</span></label>
      <p className="hint">季節配賦済みの場合は二重計上を避けるため、平準化を停止します。</p>
      <label>別請求の部品・材料費（円、省略可。労務費から除外）<input inputMode="numeric" value={materials} onChange={e => set_materials(e.target.value)} /></label>
      <label>月次費用・人時の出典<input value={source} onChange={e => set_source(e.target.value)} required /></label>
      <label>根拠資料の日付<input type="date" value={source_date} onChange={e => set_source_date(e.target.value)} required /></label>
      <label>根拠参照ID<input value={evidence_ref} onChange={e => set_evidence_ref(e.target.value)} required /></label>
      <label>根拠の説明<input value={evidence_notes} onChange={e => set_evidence_notes(e.target.value)} required /></label>
      <button disabled={busy}>{busy ? '比較中…' : '請求月と12か月平準化を比較'}</button>
    </form>
    {error && <p role="alert" className="error">{error}</p>}
    {preview && <section className="result"><h2>生単価と平準化の比較</h2>{preview.blockers.map(item => <p key={item}>確認が必要: {item}</p>)}<div className="rate-compare"><article className="rate-box"><h3>{months[Number(invoice_month) - 1]} 請求月の生単価</h3><output>{preview.raw_invoice_month_rate == null ? '算定停止' : `${Math.round(preview.raw_invoice_month_rate).toLocaleString()} 円/人時`}</output><p>請求月費用 ÷ 同月請求可能人時</p></article><article className="rate-box"><h3>12か月の平準化単価</h3><output>{preview.smoothed_rate == null ? '利用不可' : `${Math.round(preview.smoothed_rate).toLocaleString()} 円/人時`}</output><p>{preview.total_allocable_cost_yen == null ? '費用合計不明' : `${preview.total_allocable_cost_yen.toLocaleString()} 円`} ÷ {preview.total_billable_hours == null ? '人時合計不明' : `${preview.total_billable_hours.toLocaleString()} 人時`}</p></article></div><p className="hint">{preview.formula}</p><button type="button" onClick={save} disabled={busy || !preview.available}>平準化候補を共通ストアへ保存</button></section>}
    {version && <section className="result"><h2>{version.calculation.candidate_yen_per_person_hour == null ? '候補を確定できません' : `未承認候補 ${Math.round(version.calculation.candidate_yen_per_person_hour).toLocaleString()} 円/人時`}</h2><p>状態: {version.status}。人の承認前は labor_rate を作成しません。</p>{version.calculation.unknowns.map(item => <p key={item}>停止理由: {item}</p>)}{version.status === 'draft' && <div className="approval"><h3>人による承認</h3><label>承認者<input value={approved_by} onChange={e => set_approved_by(e.target.value)} /></label><label>承認理由<input value={approval_reason} onChange={e => set_approval_reason(e.target.value)} /></label><button type="button" disabled={busy || !approved_by.trim() || !approval_reason.trim()} onClick={approve}>平準化単価を承認</button></div>}</section>}
  </main>;
}
