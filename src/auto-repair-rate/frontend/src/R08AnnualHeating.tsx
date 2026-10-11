import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';
import type { RateVersion } from './types';

const today = new Date().toISOString().slice(0, 10);
type Preview = { available: boolean; blockers: string[]; annual_heating_rate: number | null; annual_base_rate: number | null; candidate_yen_per_person_hour: number | null; annual_billable_hours: number | null };

export default function R08AnnualHeating() {
  const [period_start, set_period_start] = useState(`${today.slice(0, 4)}-01-01`);
  const [period_end, set_period_end] = useState(`${today.slice(0, 4)}-12-31`);
  const [heating, set_heating] = useState('600000');
  const [other_cost, set_other_cost] = useState('6600000');
  const [billable_hours, set_billable_hours] = useState('1200');
  const [materials, set_materials] = useState('');
  const [source, set_source] = useState('架空シミュレータ');
  const [source_date, set_source_date] = useState(today);
  const [evidence_ref, set_evidence_ref] = useState('架空例 R08-2026-01');
  const [evidence_notes, set_evidence_notes] = useState('説明用の年間暖房費・年間人時です。');
  const [preview, set_preview] = useState<Preview | null>(null);
  const [version, set_version] = useState<RateVersion | null>(null);
  const [approved_by, set_approved_by] = useState('');
  const [approval_reason, set_approval_reason] = useState('');
  const [error, set_error] = useState('');
  const [busy, set_busy] = useState(false);
  const payload = () => ({ annual_period_start: period_start, annual_period_end: period_end, source_date, effective_from: today,
    annual_heating_cost_yen: heating === '' ? null : Number(heating), other_allocable_cost_yen: other_cost === '' ? null : Number(other_cost),
    annual_billable_hours: billable_hours === '' ? null : Number(billable_hours), materials_yen: materials === '' ? null : Number(materials), source, evidence_ref, evidence_notes });
  async function calculate(event: FormEvent) {
    event.preventDefault(); set_busy(true); set_error(''); set_version(null);
    try { const response = await fetch('/api/auto-repair-rate/R08/rates/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) }); if (!response.ok) throw new Error(await response.text()); set_preview(await response.json()); }
    catch (e) { set_error(e instanceof Error ? e.message : '計算に失敗しました'); } finally { set_busy(false); }
  }
  async function save() { set_busy(true); set_error(''); try { const response = await fetch('/api/auto-repair-rate/R08/proposals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) }); if (!response.ok) throw new Error(await response.text()); set_version(await response.json()); } catch (e) { set_error(e instanceof Error ? e.message : '保存に失敗しました'); } finally { set_busy(false); } }
  async function approve() { if (!version?.calculation.candidate_yen_per_person_hour) return; set_busy(true); try { set_version(await api.approve_proposal(version.proposal_id, { approved_yen_per_person_hour: version.calculation.candidate_yen_per_person_hour, effective_from: today, approved_by, approval_reason })); } catch (e) { set_error(e instanceof Error ? e.message : '承認に失敗しました'); } finally { set_busy(false); } }
  return <main className="app-shell r08-screen"><style>{`.r08-screen .annual-card{padding:16px;background:#e6efeb;border-left:5px solid #528679;line-height:1.65}.r08-screen .annual-rate{font-size:27px;font-weight:800;color:#17665e}`}</style>
    <header><p className="eyebrow">R08　年間固定費配賦</p><h1>暖房費を<br />年間へ配賦</h1><p>暖房費もその他の配賦費用も、同じ年間請求可能人時で割ります。</p></header>
    <aside className="fictional">架空の初期値です。実際の暖房費・請求可能人時ではありません。</aside>
    <form onSubmit={calculate}>
      <label>年間対象期間・開始日<input type="date" value={period_start} onChange={e => set_period_start(e.target.value)} required /></label>
      <label>年間対象期間・終了日<input type="date" value={period_end} onChange={e => set_period_end(e.target.value)} required /></label>
      <div className="annual-card"><strong>通年配賦</strong><br />冬季だけの上乗せは行いません。年間暖房費 ÷ 年間請求可能人時 ＋ その他年間配賦費用 ÷ 同じ年間請求可能人時</div>
      <label>暖房費年額（円）<input inputMode="numeric" value={heating} onChange={e => set_heating(e.target.value)} /></label>
      <label>その他の年間配賦費用（円）<input inputMode="numeric" value={other_cost} onChange={e => set_other_cost(e.target.value)} /></label>
      <label>年間請求可能人時 H_period_bill（年全体）<input inputMode="decimal" value={billable_hours} onChange={e => set_billable_hours(e.target.value)} /></label>
      <label>別請求の部品・材料費（円、省略可。労務費から除外）<input inputMode="numeric" value={materials} onChange={e => set_materials(e.target.value)} /></label>
      <label>費用と人時の出典<input value={source} onChange={e => set_source(e.target.value)} required /></label>
      <label>根拠資料の日付<input type="date" value={source_date} onChange={e => set_source_date(e.target.value)} required /></label>
      <label>根拠参照ID<input value={evidence_ref} onChange={e => set_evidence_ref(e.target.value)} required /></label>
      <label>根拠の説明<input value={evidence_notes} onChange={e => set_evidence_notes(e.target.value)} required /></label>
      <button disabled={busy}>{busy ? '計算中…' : '年間単価を計算'}</button>
    </form>
    {error && <p role="alert" className="error">{error}</p>}
    {preview && <section className="result" aria-live="polite"><h2>年間配賦の結果</h2>{preview.blockers.map(item => <p key={item}>確認が必要: {item}</p>)}<p>対象期間: {period_start} 〜 {period_end}</p><p>年間請求可能人時: {preview.annual_billable_hours ?? '不明'}</p><p>暖房費の年単価影響: {preview.annual_heating_rate == null ? '算定停止' : `${Math.round(preview.annual_heating_rate).toLocaleString()} 円/人時`}</p><p>その他費用: {preview.annual_base_rate == null ? '算定停止' : `${Math.round(preview.annual_base_rate).toLocaleString()} 円/人時`}</p><p className="annual-rate">通年候補: {preview.candidate_yen_per_person_hour == null ? '算定停止' : `${Math.round(preview.candidate_yen_per_person_hour).toLocaleString()} 円/人時`}</p><button type="button" disabled={busy || !preview.available} onClick={save}>年間候補を共通ストアに保存</button></section>}
    {version && <section className="result"><h2>{version.calculation.candidate_yen_per_person_hour == null ? '候補を確定できません' : `未承認候補 ${Math.round(version.calculation.candidate_yen_per_person_hour).toLocaleString()} 円/人時`}</h2><p>状態: {version.status}。人の承認前は labor_rate を作成しません。</p>{version.calculation.unknowns.map(item => <p key={item}>停止理由: {item}</p>)}{version.status === 'draft' && <div className="approval"><h3>人による承認</h3><label>承認者<input value={approved_by} onChange={e => set_approved_by(e.target.value)} /></label><label>承認理由<input value={approval_reason} onChange={e => set_approval_reason(e.target.value)} /></label><button type="button" disabled={busy || !approved_by.trim() || !approval_reason.trim()} onClick={approve}>年間単価を承認</button></div>}</section>}
  </main>;
}
