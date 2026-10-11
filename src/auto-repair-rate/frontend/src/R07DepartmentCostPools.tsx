import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';
import type { RateVersion } from './types';

const categories = ['整備', '鈑金塗装'] as const;
type Category = typeof categories[number];
const today = new Date().toISOString().slice(0, 10);

export default function R07DepartmentCostPools() {
  const [direct, set_direct] = useState<Record<Category, string>>({ 整備: '800000', 鈑金塗装: '500000' });
  const [keys, set_keys] = useState<Record<Category, string>>({ 整備: '3', 鈑金塗装: '2' });
  const [hours, set_hours] = useState<Record<Category, string>>({ 整備: '1200', 鈑金塗装: '700' });
  const [util, set_util] = useState<Record<Category, string>>({ 整備: '0.75', 鈑金塗装: '0.7' });
  const [common_cost, set_common_cost] = useState('1000000');
  const [materials, set_materials] = useState('');
  const [selected, set_selected] = useState<Category | ''>('');
  const [allocation_confirmed, set_allocation_confirmed] = useState(false);
  const [source, set_source] = useState('架空シミュレータ');
  const [source_date, set_source_date] = useState(today);
  const [evidence_ref, set_evidence_ref] = useState('架空例 R07-2026-01');
  const [evidence_notes, set_evidence_notes] = useState('説明用の架空費用・配賦キー・人時です。');
  const [preview, set_preview] = useState<any>(null);
  const [version, set_version] = useState<RateVersion | null>(null);
  const [approved_by, set_approved_by] = useState('');
  const [approval_reason, set_approval_reason] = useState('');
  const [error, set_error] = useState('');
  const [busy, set_busy] = useState(false);
  const payload = () => ({ period_start: `${today.slice(0, 4)}-01-01`, source_date, effective_from: today,
    direct_cost_yen: Object.fromEntries(categories.map(c => [c, direct[c] === '' ? null : Number(direct[c])])),
    shared_cost_yen: common_cost === '' ? null : Number(common_cost),
    allocation_key: Object.fromEntries(categories.map(c => [c, keys[c] === '' ? null : Number(keys[c])])),
    total_person_hours: Object.fromEntries(categories.map(c => [c, hours[c] === '' ? null : Number(hours[c])])),
    u_period: Object.fromEntries(categories.map(c => [c, util[c] === '' ? null : Number(util[c])])), selected_category: selected || null,
    allocation_confirmed, materials_yen: materials === '' ? null : Number(materials), source, evidence_ref, evidence_notes });
  async function calculate(event: FormEvent) {
    event.preventDefault(); set_busy(true); set_error(''); set_version(null);
    try { const res = await fetch('/api/auto-repair-rate/R07/rates/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) }); if (!res.ok) throw new Error(await res.text()); set_preview(await res.json()); }
    catch (e) { set_error(e instanceof Error ? e.message : '計算に失敗しました'); } finally { set_busy(false); }
  }
  async function save() {
    set_busy(true); set_error('');
    try { const res = await fetch('/api/auto-repair-rate/R07/proposals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) }); if (!res.ok) throw new Error(await res.text()); set_version(await res.json()); }
    catch (e) { set_error(e instanceof Error ? e.message : '保存に失敗しました'); } finally { set_busy(false); }
  }
  async function approve() { if (!version?.calculation.candidate_yen_per_person_hour) return; set_busy(true); try { set_version(await api.approve_proposal(version.proposal_id, { approved_yen_per_person_hour: version.calculation.candidate_yen_per_person_hour, effective_from: today, approved_by, approval_reason })); } catch (e) { set_error(e instanceof Error ? e.message : '承認に失敗しました'); } finally { set_busy(false); } }
  return <main className="app-shell r07-screen"><style>{`.r07-screen .category-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.r07-screen .category-card{background:#fff;border:1px solid #c7d3cf;border-radius:7px;padding:14px;display:grid;gap:12px}.r07-screen output{font-size:23px;font-weight:800;color:#17665e}.r07-screen .allocation-confirm{padding:12px;background:#e6efeb;line-height:1.6}@media(max-width:520px){.r07-screen .category-grid{grid-template-columns:1fr}}`}</style>
    <header><p className="eyebrow">R07　部門別費用プール</p><h1>2つの作業区分へ<br />共通費を配賦</h1><p>整備と鈑金塗装を別々に試算し、元の共通費と配賦後合計が一致するか確認します。</p></header>
    <aside className="fictional">架空の初期値です。実工場の費用・配賦キー・人時ではありません。</aside>
    <form onSubmit={calculate}>
      <div className="category-grid">{categories.map(category => <article className="category-card" key={category}><h2>{category}</h2>
        <label>個別費用 C[{category}]（円）<input inputMode="numeric" value={direct[category]} onChange={e => set_direct({ ...direct, [category]: e.target.value })} /></label>
        <label>共通費の配賦キー<input inputMode="decimal" value={keys[category]} onChange={e => set_keys({ ...keys, [category]: e.target.value })} /></label>
        <label>総労働人時 H_total[{category}]<input inputMode="decimal" value={hours[category]} onChange={e => set_hours({ ...hours, [category]: e.target.value })} /></label>
        <label>請求可能割合 u_period[{category}]<input type="number" min="0" max="1" step="0.01" value={util[category]} onChange={e => set_util({ ...util, [category]: e.target.value })} /></label>
        {preview && <output>{preview.rate_yen_per_person_hour?.[category] == null ? '算定停止' : `${Math.round(preview.rate_yen_per_person_hour[category]).toLocaleString()} 円/人時`}</output>}
      </article>)}</div>
      <label>配賦する共通費合計（円）<input inputMode="numeric" value={common_cost} onChange={e => set_common_cost(e.target.value)} /></label>
      <p className="hint">カテゴリ単価 = [個別費用 + 共通費配賦額] ÷ [H_total × u_period]。配賦キーは費用割合など明示した指標を入力します。</p>
      <label>別請求の塗料・材料費（円、省略可。労務費から除外）<input inputMode="numeric" value={materials} onChange={e => set_materials(e.target.value)} /></label>
      <label>費用・キー・人時の出典<input value={source} onChange={e => set_source(e.target.value)} required /></label>
      <label>根拠資料の日付<input type="date" value={source_date} onChange={e => set_source_date(e.target.value)} required /></label>
      <label>根拠参照ID<input value={evidence_ref} onChange={e => set_evidence_ref(e.target.value)} required /></label>
      <label>根拠の説明<input value={evidence_notes} onChange={e => set_evidence_notes(e.target.value)} required /></label>
      <label>共有候補にするカテゴリ<select value={selected} onChange={e => set_selected(e.target.value as Category | '')}><option value="">未選択</option>{categories.map(c => <option key={c}>{c}</option>)}</select></label>
      <label className="allocation-confirm"><span><input type="checkbox" checked={allocation_confirmed} onChange={e => set_allocation_confirmed(e.target.checked)} style={{ width: 22, minHeight: 22, verticalAlign: 'middle', marginRight: 8 }} />共通費の配賦キーと各金額を確認し、元費用との一致を確認する</span></label>
      <button disabled={busy}>{busy ? '計算中…' : 'カテゴリ別単価を計算'}</button>
    </form>
    {error && <p role="alert" className="error">{error}</p>}
    {preview && <section className="result"><h2>配賦検算</h2><p>元共通費: {preview.source_shared_cost_yen ?? '不明'} 円 / 配賦合計: {preview.reconciled_shared_cost_yen} 円 / 一致: {String(preview.reconciles)}</p>{preview.blockers.map((item: string) => <p key={item}>確認が必要: {item}</p>)}<div className="category-grid">{categories.map(c => <article className="category-card" key={c}><h3>{c}</h3><p>共通費配賦: {preview.allocated_shared_cost_yen?.[c] ?? '不明'} 円</p><p>カテゴリ費用 C[{c}]: {preview.category_cost_yen?.[c] ?? '不明'} 円</p><p>請求可能人時 H_total×u_period: {preview.denominator_billable_hours?.[c] ?? '不明'}</p><output>{preview.rate_yen_per_person_hour?.[c] == null ? '算定停止' : `${Math.round(preview.rate_yen_per_person_hour[c]).toLocaleString()} 円/人時`}</output></article>)}</div>
      <button type="button" onClick={save} disabled={busy || !preview.available || !selected || !allocation_confirmed}>選んだカテゴリを共通ストアに候補保存</button></section>}
    {version && <section className="result"><h2>{version.calculation.candidate_yen_per_person_hour == null ? '候補を確定できません' : `未承認候補 ${Math.round(version.calculation.candidate_yen_per_person_hour).toLocaleString()} 円/人時`}</h2><p>状態: {version.status}。人の承認前は labor_rate を作成しません。</p>{version.calculation.basis.map((row, i) => <p key={i}>{row.label}: {String(row.value)} {row.unit}</p>)}{version.status === 'draft' && <div className="approval"><h3>人による承認</h3><label>承認者<input value={approved_by} onChange={e => set_approved_by(e.target.value)} /></label><label>承認理由<input value={approval_reason} onChange={e => set_approval_reason(e.target.value)} /></label><button type="button" disabled={busy || !approved_by.trim() || !approval_reason.trim()} onClick={approve}>選択カテゴリを承認</button></div>}</section>}
  </main>;
}
