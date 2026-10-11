import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';
import type { RateVersion } from './types';

const today = new Date().toISOString().slice(0, 10);
type Scenario = '' | 'annual_baseline' | 'winter_scenario';
type Preview = { available: boolean; baseline_available: boolean; winter_available: boolean; blockers: string[]; annual_baseline_rate: number | null; winter_candidate_rate: number | null; delta_yen_per_person_hour: number | null; annual_impact_yen: number | null; applied_by_default: false };

export default function R09WinterAllocation() {
  const [winter_cost, set_winter_cost] = useState('300000');
  const [winter_hours, set_winter_hours] = useState('240');
  const [baseline, set_baseline] = useState('6000');
  const [annual_hours, set_annual_hours] = useState('1200');
  const [start_month, set_start_month] = useState('11');
  const [end_month, set_end_month] = useState('3');
  const [scenario, set_scenario] = useState<Scenario>('');
  const [policy_confirmed, set_policy_confirmed] = useState(false);
  const [source, set_source] = useState('架空シミュレータ');
  const [source_date, set_source_date] = useState(today);
  const [evidence_ref, set_evidence_ref] = useState('架空例 R09-2026-01');
  const [evidence_notes, set_evidence_notes] = useState('説明用の架空冬季費用・人時・年間基準です。');
  const [materials, set_materials] = useState('');
  const [preview, set_preview] = useState<Preview | null>(null);
  const [version, set_version] = useState<RateVersion | null>(null);
  const [approved_by, set_approved_by] = useState('');
  const [approval_reason, set_approval_reason] = useState('');
  const [error, set_error] = useState('');
  const [busy, set_busy] = useState(false);
  const payload = () => ({ annual_period_start: `${today.slice(0, 4)}-01-01`, annual_period_end: `${today.slice(0, 4)}-12-31`,
    winter_start_month: Number(start_month), winter_end_month: Number(end_month), source_date, effective_from: today,
    winter_cost_yen: winter_cost === '' ? null : Number(winter_cost), winter_billable_hours: winter_hours === '' ? null : Number(winter_hours),
    annual_baseline_rate: baseline === '' ? null : Number(baseline), annual_billable_hours: annual_hours === '' ? null : Number(annual_hours),
    selected_scenario: scenario || null, price_policy_confirmed: policy_confirmed, materials_yen: materials === '' ? null : Number(materials),
    source, evidence_ref, evidence_notes });
  async function calculate(event: FormEvent) { event.preventDefault(); set_busy(true); set_error(''); set_version(null); try { const response = await fetch('/api/auto-repair-rate/R09/rates/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) }); if (!response.ok) throw new Error(await response.text()); set_preview(await response.json()); } catch (e) { set_error(e instanceof Error ? e.message : '比較に失敗しました'); } finally { set_busy(false); } }
  async function save() { set_busy(true); set_error(''); try { const response = await fetch('/api/auto-repair-rate/R09/proposals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) }); if (!response.ok) throw new Error(await response.text()); set_version(await response.json()); } catch (e) { set_error(e instanceof Error ? e.message : '保存に失敗しました'); } finally { set_busy(false); } }
  async function approve() { if (!version?.calculation.candidate_yen_per_person_hour) return; set_busy(true); try { set_version(await api.approve_proposal(version.proposal_id, { approved_yen_per_person_hour: version.calculation.candidate_yen_per_person_hour, effective_from: today, approved_by, approval_reason })); } catch (e) { set_error(e instanceof Error ? e.message : '承認に失敗しました'); } finally { set_busy(false); } }
  return <main className="app-shell r09-screen"><style>{`.r09-screen .compare-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.r09-screen .compare-card{padding:16px;background:#fff;border:1px solid #c7d3cf;border-radius:7px}.r09-screen .compare-card output{display:block;font-size:24px;font-weight:800;color:#17665e;margin:10px 0}.r09-screen .policy-note{padding:14px;background:#f4ecd9;border-left:5px solid #d99a31;line-height:1.65}@media(max-width:500px){.r09-screen .compare-grid{grid-template-columns:1fr}}`}</style>
    <header><p className="eyebrow">R09　冬季費用の季節別配賦</p><h1>冬季案を通年基準と<br />比べて確認</h1><p>冬季費用を冬季請求可能人時に配賦し、差額と冬季だけに適用した場合の年間影響を表示します。</p></header>
    <aside className="fictional">架空の初期値です。冬季単価は既定で未選択・未適用です。気象情報で費用や単価を推定しません。</aside>
    <form onSubmit={calculate}>
      <label>冬季対象・開始月<input type="number" min="1" max="12" value={start_month} onChange={e => set_start_month(e.target.value)} /></label>
      <label>冬季対象・終了月<input type="number" min="1" max="12" value={end_month} onChange={e => set_end_month(e.target.value)} /></label>
      <label>冬季費用（円）<input inputMode="numeric" value={winter_cost} onChange={e => set_winter_cost(e.target.value)} /></label>
      <label>冬季請求可能人時（必須）<input inputMode="decimal" value={winter_hours} onChange={e => set_winter_hours(e.target.value)} placeholder="不明または0なら試算停止" /></label>
      <label>明示した年間基準単価（円/人時）<input inputMode="decimal" value={baseline} onChange={e => set_baseline(e.target.value)} /></label>
      <label>年間請求可能人時（年間影響表示用）<input inputMode="decimal" value={annual_hours} onChange={e => set_annual_hours(e.target.value)} /></label>
      <label>別請求の部品・材料費（円、省略可。労務費から除外）<input inputMode="numeric" value={materials} onChange={e => set_materials(e.target.value)} /></label>
      <label>費用・時間・年間基準の出典<input value={source} onChange={e => set_source(e.target.value)} required /></label>
      <label>根拠資料の日付<input type="date" value={source_date} onChange={e => set_source_date(e.target.value)} required /></label>
      <label>根拠参照ID<input value={evidence_ref} onChange={e => set_evidence_ref(e.target.value)} required /></label>
      <label>根拠の説明<input value={evidence_notes} onChange={e => set_evidence_notes(e.target.value)} required /></label>
      <button disabled={busy}>{busy ? '比較中…' : '年間基準と冬季案を比較'}</button>
    </form>
    {error && <p role="alert" className="error">{error}</p>}
    {preview && <section className="result"><h2>比較結果</h2>{preview.blockers.map(item => <p key={item}>確認が必要: {item}</p>)}<div className="compare-grid"><article className="compare-card"><h3>年間基準</h3><output>{preview.annual_baseline_rate == null ? '不明' : `${Math.round(preview.annual_baseline_rate).toLocaleString()} 円/人時`}</output><p>通年費用の比較基準</p></article><article className="compare-card"><h3>冬季のみ配賦した場合</h3><output>{preview.winter_candidate_rate == null ? '算定停止' : `${Math.round(preview.winter_candidate_rate).toLocaleString()} 円/人時`}</output><p>基準との差: {preview.delta_yen_per_person_hour == null ? '不明' : `${Math.round(preview.delta_yen_per_person_hour).toLocaleString()} 円/人時`}</p><p>冬季だけに適用した場合の年間影響: {preview.annual_impact_yen == null ? '不明' : `${Math.round(preview.annual_impact_yen).toLocaleString()} 円/年`}</p></article></div>
      <p className="policy-note">冬季候補は自動適用しません。共有ストアに保存する案を選択し、人が価格方針を確認した後、別途人が承認します。</p>
      <label>共有候補にする案<select value={scenario} onChange={e => { set_scenario(e.target.value as Scenario); set_policy_confirmed(false); }}><option value="">未選択（既定）</option><option value="annual_baseline">年間基準</option><option value="winter_scenario">冬季候補</option></select></label>
      {scenario === 'winter_scenario' && <label className="policy-note"><span><input type="checkbox" checked={policy_confirmed} onChange={e => set_policy_confirmed(e.target.checked)} style={{ width: 22, minHeight: 22, verticalAlign: 'middle', marginRight: 8 }} />顧客受容を含む価格方針を確認した</span></label>}
      <button type="button" onClick={save} disabled={busy || !scenario || (scenario === 'annual_baseline' && !preview.baseline_available) || (scenario === 'winter_scenario' && (!preview.winter_available || !policy_confirmed))}>選択案を未承認候補として保存</button></section>}
    {version && <section className="result"><h2>{version.calculation.candidate_yen_per_person_hour == null ? '候補を確定できません' : `未承認候補 ${Math.round(version.calculation.candidate_yen_per_person_hour).toLocaleString()} 円/人時`}</h2><p>状態: {version.status}。冬季案は既定適用せず、人による共通承認が必要です。</p>{version.calculation.unknowns.map(item => <p key={item}>停止理由: {item}</p>)}{version.status === 'draft' && <div className="approval"><h3>人による承認</h3><label>承認者<input value={approved_by} onChange={e => set_approved_by(e.target.value)} /></label><label>承認理由<input value={approval_reason} onChange={e => set_approval_reason(e.target.value)} /></label><button type="button" disabled={busy || !approved_by.trim() || !approval_reason.trim()} onClick={approve}>選択した価格案を承認</button></div>}</section>}
  </main>;
}
