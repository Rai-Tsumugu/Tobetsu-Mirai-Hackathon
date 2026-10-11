import { useEffect, useState } from 'react';
import type { ComponentType, FormEvent } from 'react';
import { api } from './api';
import type { RateHistoryRecord, RateVersion } from './types';

const today = new Date().toISOString().slice(0, 10);

function R15Screen() {
  const [cost, set_cost] = useState('7200000');
  const [hours, set_hours] = useState('1600');
  const [materials_excluded, set_materials_excluded] = useState(false);
  const [scenario_name, set_scenario_name] = useState('年間');
  const [source_date, set_source_date] = useState(today);
  const [period_start, set_period_start] = useState(`${today.slice(0, 4)}-01-01`);
  const [period_end, set_period_end] = useState(`${today.slice(0, 4)}-12-31`);
  const [source_name, set_source_name] = useState('架空シミュレータ');
  const [evidence_ref, set_evidence_ref] = useState('架空例 R15');
  const [evidence_notes, set_evidence_notes] = useState('費用合計と期間稼働の架空シミュレーション');
  const [u_period, set_u_period] = useState('0.75');
  const [u_period_low, set_u_period_low] = useState('0.60');
  const [u_period_high, set_u_period_high] = useState('0.90');
  const [scenario_results, set_scenario_results] = useState<{ label: string; value: number | null; u_period: string }[]>([]);
  const [effective_from, set_effective_from] = useState(today);
  const [version, set_version] = useState<RateVersion | null>(null);
  const [approved_by, set_approved_by] = useState('');
  const [approval_reason, set_approval_reason] = useState('');
  const [error, set_error] = useState('');
  const [busy, set_busy] = useState(false);

  useEffect(() => { set_version(null); set_scenario_results([]); }, [cost, hours, materials_excluded, scenario_name, source_date, period_start, period_end, source_name, evidence_ref, evidence_notes, u_period, u_period_low, u_period_high, effective_from]);

  async function calculate_rate(event: FormEvent) {
    event.preventDefault(); set_busy(true); set_error(''); set_version(null);
    if (!materials_excluded) { set_error('別請求の部品・材料費を除外した確認が必要です'); set_busy(false); return; }
    const payload = { allocable_cost_yen: cost === '' ? null : Number(cost), H_period_total: hours === '' ? null : Number(hours), u_period: u_period === '' ? null : Number(u_period), materials_excluded, period_start, period_end, effective_from, source: source_name, source_date, evidence_ref, evidence_notes: `${evidence_notes}; シナリオ=${scenario_name}` };
    try { const response = await fetch('/api/auto-repair-rate/R15/proposals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); if (!response.ok) throw new Error(await response.text()); set_version(await response.json()); }
    catch (e) { set_error(e instanceof Error ? e.message : '計算に失敗しました'); }
    finally { set_busy(false); }
  }

  async function approve_rate() {
    if (!version) return;
    set_busy(true); set_error('');
    try { set_version(await api.approve_proposal(version.proposal_id, { approved_yen_per_person_hour: version.calculation.candidate_yen_per_person_hour!, effective_from, approved_by, approval_reason })); }
    catch (e) { set_error(e instanceof Error ? e.message : '承認に失敗しました'); }
    finally { set_busy(false); }
  }

  async function compare_scenarios() {
    set_busy(true); set_error('');
    const choices = [{ label: '低稼働', u_period: u_period_low }, { label: '標準', u_period }, { label: '高稼働', u_period: u_period_high }];
    try {
      const results = await Promise.all(choices.map(async (choice) => {
        const payload = { allocable_cost_yen: cost === '' ? null : Number(cost), H_period_total: hours === '' ? null : Number(hours), u_period: choice.u_period === '' ? null : Number(choice.u_period), materials_excluded, period_start, period_end, effective_from, source: source_name, source_date, evidence_ref, evidence_notes };
        const response = await fetch('/api/auto-repair-rate/R15/rates/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        if (!response.ok) throw new Error(await response.text());
        const result = await response.json();
        return { label: choice.label, value: result.candidate_yen_per_person_hour, u_period: choice.u_period };
      }));
      set_scenario_results(results);
    } catch (error) { set_error(error instanceof Error ? error.message : 'シナリオを比較できませんでした'); }
    finally { set_busy(false); }
  }

  return <main className="app-shell">
    <style>{`
      :root{font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;color:#182e35;background:#e8eeeb;font-synthesis:none}
      *{box-sizing:border-box}body{margin:0;background:#e8eeeb}button,input,select{font:inherit}button{min-height:52px;border:0;border-radius:5px;background:#17665e;color:#fff;font-weight:700;padding:12px 18px;cursor:pointer}button:disabled{opacity:.56;cursor:wait}
      :focus-visible{outline:3px solid #df9b33;outline-offset:3px}.app-shell{max-width:760px;margin:0 auto;min-height:100vh;background:#f7f8f3;padding:26px clamp(18px,5vw,42px) 60px;border-top:9px solid #17665e}
      header{padding:12px 0 20px;border-bottom:1px solid #c7d3cf}header h1{font-size:clamp(27px,7vw,40px);line-height:1.2;letter-spacing:.02em;margin:6px 0 10px}header p:last-child{line-height:1.7;margin:0;color:#496067}.eyebrow{color:#17665e;font-weight:700;margin:0;font-size:13px;letter-spacing:.08em}
      .fictional{margin:18px 0;padding:14px 16px;border-left:5px solid #d99a31;background:#f4ecd9;color:#4e3d20;line-height:1.55;font-weight:700}
      form{display:grid;gap:17px;margin:22px 0}label{display:grid;gap:7px;font-size:15px;font-weight:700;color:#213b41}input,select{width:100%;min-height:49px;border:1px solid #96aaa4;border-radius:4px;padding:10px 12px;background:#fff;color:#182e35}input:focus,select:focus{border-color:#17665e}.hint{margin:0;color:#4d6367;font-size:13px;line-height:1.65}form button{width:100%}
      .result{margin-top:24px;padding:20px 0;border-top:3px solid #17665e;border-bottom:1px solid #c7d3cf}.result h2{font-size:25px;margin:0 0 12px;color:#164f49}.result p{line-height:1.65}.result ul{padding-left:22px;line-height:1.9}.approval{margin-top:25px;padding-top:18px;border-top:1px dashed #91a49e;display:grid;gap:15px}.approval h3{margin:0}.approved{font-weight:700;color:#17665e}.error{color:#8a251f;background:#f8e6e3;padding:12px}.job-range{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.job-range label{font-size:13px}.job-note{padding:12px 14px;background:#e6efeb;border-left:4px solid #528679;line-height:1.55}
      @media(max-width:430px){.app-shell{padding-top:18px}.job-range{grid-template-columns:1fr 1fr}.job-range label:last-child{grid-column:1/-1}}
      @media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
    `}</style>
    <header><p className="eyebrow">統合フォーム　費用・稼働・根拠</p><h1>工場の時間単価を<br />見直す</h1><p>費用と期間の請求可能人時、材料除外、根拠、有効日を確認してから人が承認します。</p></header>
    <aside className="fictional">架空デモ値です。実測値や地域相場ではありません。入力はローカルAPIに保存します。</aside>
    <form onSubmit={calculate_rate}><fieldset disabled={busy} style={{ border: 0, padding: 0, margin: 0, display: 'grid', gap: 17 }}>
      <label>年度・シナリオ<select value={scenario_name} onChange={e => set_scenario_name(e.target.value)}><option>年間</option><option>冬季条件</option><option>平準化条件</option></select></label>
      <label>期間配賦費用（円）<input inputMode="numeric" value={cost} onChange={e => set_cost(e.target.value)} placeholder="不明なら空欄" /></label>
      <label>期間の総労働人時<input inputMode="decimal" value={hours} onChange={e => set_hours(e.target.value)} placeholder="不明なら空欄" /></label>
      <label>対象期間の開始日<input type="date" value={period_start} onChange={e => set_period_start(e.target.value)} /></label>
      <label>対象期間の終了日<input type="date" value={period_end} onChange={e => set_period_end(e.target.value)} /></label>
      <label>期間請求可能割合 u_period<input inputMode="decimal" min="0" max="1" step="0.01" value={u_period} onChange={e => set_u_period(e.target.value)} placeholder="不明なら空欄" /></label>
      <label>低シナリオ u_period<input inputMode="decimal" min="0" max="1" step="0.01" value={u_period_low} onChange={e => set_u_period_low(e.target.value)} /></label>
      <label>高シナリオ u_period<input inputMode="decimal" min="0" max="1" step="0.01" value={u_period_high} onChange={e => set_u_period_high(e.target.value)} /></label>
      <button type="button" disabled={busy} onClick={() => void compare_scenarios()}>低・標準・高シナリオを比較</button>
      {scenario_results.map((scenario) => <button key={scenario.label} type="button" onClick={() => { set_u_period(scenario.u_period); set_scenario_name(scenario.label); }}>{scenario.label}: {scenario.value == null ? '試算停止' : `${Math.round(scenario.value).toLocaleString()} 円/人時`}　この割合を選択</button>)}
      <label><input type="checkbox" checked={materials_excluded} onChange={e => set_materials_excluded(e.target.checked)} /> 別請求の部品・材料費を配賦額から除外した</label>
      <label>根拠資料の日付<input type="date" value={source_date} onChange={e => set_source_date(e.target.value)} /></label>
      <label>資料の出所<input value={source_name} onChange={e => set_source_name(e.target.value)} /></label>
      <label>根拠参照ID<input value={evidence_ref} onChange={e => set_evidence_ref(e.target.value)} /></label>
      <label>根拠・見直しメモ<input value={evidence_notes} onChange={e => set_evidence_notes(e.target.value)} /></label>
      <label>適用開始日<input type="date" value={effective_from} onChange={e => set_effective_from(e.target.value)} required /></label>
      <p className="hint">期間分母 = 期間総労働人時 × u_period。案件人時は別計算し、総人時基準なら案件請求可能割合を1回適用します。</p>
      <button disabled={busy}>{busy ? '処理中…' : '候補を試算'}</button>
    </fieldset></form>
    {error && <p role="alert" className="error">{error}</p>}
    {version && <section className="result" aria-live="polite">
      <h2>{version.calculation.candidate_yen_per_person_hour == null ? '数値候補を出せません' : `候補 ${Math.round(version.calculation.candidate_yen_per_person_hour).toLocaleString()} 円 / 人時`}</h2>
      <p>状態: {version.status === 'blocked' ? '入力待ち' : version.status === 'approved' ? '人が承認済み' : '未承認の候補'}</p>
      {version.calculation.unknowns.length > 0 && <p>不足・停止理由: {version.calculation.unknowns.join('、')}</p>}
      {version.calculation.job_unknowns.length > 0 && <p>案件人時の不足: {version.calculation.job_unknowns.join('、')}</p>}
      {version.calculation.job_billable_person_hours && <p>案件請求人時（低／標準／高）: {version.calculation.job_billable_person_hours.low} ／ {version.calculation.job_billable_person_hours.typical} ／ {version.calculation.job_billable_person_hours.high} 人時</p>}
      {version.calculation.excluded_items.map(item => <p key={item.cost_id}>除外: {item.label}（別請求の部品・材料）</p>)}
      <ul>{version.calculation.basis.map((row, i) => <li key={i}>{row.label}: {String(row.value)} {row.unit}</li>)}</ul>
      {version.labor_rate && <p className="approved">適用単価: {version.labor_rate.yen_per_person_hour.toLocaleString()} 円/人時（{version.labor_rate.effective_from}〜）</p>}
      {version.status === 'draft' && version.calculation.candidate_yen_per_person_hour != null && <div className="approval">
        <h3>人による承認</h3>
        <label>承認者<input value={approved_by} onChange={e => set_approved_by(e.target.value)} required /></label>
        <label>承認理由<input value={approval_reason} onChange={e => set_approval_reason(e.target.value)} required /></label>
        <button type="button" onClick={approve_rate} disabled={busy || !approved_by.trim() || !approval_reason.trim()}>この単価を承認して保存</button>
      </div>}
    </section>}
  </main>;
}

function SharedRecordsPanel() {
  const [recent_proposals, set_recent_proposals] = useState<RateVersion[]>([]);
  const [rate_history, set_rate_history] = useState<RateHistoryRecord[]>([]);
  const [load_error, set_load_error] = useState('');
  const [loading, set_loading] = useState(false);
  const [approved_by, set_approved_by] = useState('');
  const [approval_reason, set_approval_reason] = useState('');
  const [approval_date, set_approval_date] = useState(today);
  const [rate_as_of, set_rate_as_of] = useState(today);
  const [active_rate, set_active_rate] = useState<RateHistoryRecord | null>(null);
  const [active_rate_loaded, set_active_rate_loaded] = useState(false);

  async function refresh_records() {
    set_loading(true);
    set_load_error('');
    try {
      const [proposal_rows, rate_rows] = await Promise.all([api.list_proposals(), api.list_rates()]);
      set_recent_proposals(proposal_rows);
      set_rate_history(rate_rows);
    } catch (error) {
      set_load_error(error instanceof Error ? error.message : '記録を読み込めませんでした');
    } finally {
      set_loading(false);
    }
  }

  useEffect(() => { void refresh_records(); }, []);

  async function approve_saved(proposal_id: string) {
    try {
      const proposal = recent_proposals.find((row) => row.proposal_id === proposal_id);
      if (proposal?.calculation.candidate_yen_per_person_hour == null) return;
      await api.approve_proposal(proposal_id, { approved_yen_per_person_hour: proposal.calculation.candidate_yen_per_person_hour, effective_from: approval_date, approved_by, approval_reason });
      await refresh_records();
    } catch (error) {
      set_load_error(error instanceof Error ? error.message : '承認を保存できませんでした');
    }
  }

  async function load_active_rate() {
    try {
      const response = await fetch(`/api/auto-repair-rate/labor-rates/active?as_of=${rate_as_of}`);
      if (!response.ok) throw new Error(await response.text());
      set_active_rate(await response.json() as RateHistoryRecord | null);
      set_active_rate_loaded(true);
    } catch (error) {
      set_load_error(error instanceof Error ? error.message : '指定日の有効単価を取得できませんでした');
    }
  }

  const status_label = (status: RateVersion['status']) => ({ draft: '未承認候補', blocked: '入力待ち・停止', approved: '承認済み' })[status];
  return <section className="shared-records" aria-label="根拠と単価履歴">
    <style>{`
      .shared-records{max-width:760px;margin:0 auto;padding:24px clamp(18px,5vw,42px) 50px;background:#f7f8f3;color:#182e35;font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif}
      .shared-records h2{font-size:22px;line-height:1.35;margin:18px 0 10px}.shared-records h3{font-size:17px;margin:12px 0 6px}.shared-refresh{min-height:48px;width:100%;border:0;border-radius:5px;background:#17665e;color:#fff;font:700 15px inherit;padding:10px 14px}
      .shared-card{margin:12px 0;padding:15px;background:#fff;border:1px solid #c7d3cf;border-radius:7px;overflow-wrap:anywhere}.shared-card p,.shared-card li{line-height:1.6;margin:5px 0}.shared-muted{color:#496067}.shared-evidence{padding:10px 0;border-top:1px solid #e1e7e4}.shared-error{color:#8a251f;background:#f8e6e3;padding:10px}
    `}</style>
    <header><p className="eyebrow">共通の保存記録</p><h2>根拠・候補・承認済み単価</h2><p>方式ごとに保存した入力根拠と、社長承認後の履歴を確認できます。</p></header>
    <button type="button" className="shared-refresh" onClick={refresh_records} disabled={loading}>{loading ? '読み込み中…' : '記録を更新'}</button>
    <section className="shared-card"><h3>指定日の工場標準単価</h3><label>確認日<input type="date" value={rate_as_of} onChange={(event) => { set_rate_as_of(event.target.value); set_active_rate(null); set_active_rate_loaded(false); }} /></label><button type="button" className="shared-refresh" onClick={() => void load_active_rate()}>有効単価を確認</button>{active_rate?.labor_rate && <p><strong>{active_rate.labor_rate.yen_per_person_hour.toLocaleString()} 円/人時</strong>（{active_rate.labor_rate.effective_from}〜、{active_rate.rate_scope}）</p>}{active_rate_loaded && !active_rate?.labor_rate && <p>この日付に有効な承認済み標準単価はありません。</p>}</section>
    {load_error && <p className="shared-error" role="alert">{load_error}</p>}
    <h2>最近の候補と根拠</h2>
    {recent_proposals.length ? recent_proposals.map((proposal) => <article className="shared-card" key={proposal.proposal_id}>
      <h3>{proposal.source}　{status_label(proposal.status)}</h3>
      <p>方式: {proposal.module_id}　／　保存: {new Date(proposal.created_at).toLocaleString()}</p>
      <p>用途: {proposal.rate_type === 'internal' ? '内部原価' : '顧客請求'} ／ 範囲: {proposal.rate_scope}</p>
      {proposal.calculation.candidate_yen_per_person_hour != null && <p><strong>{proposal.status === 'approved' ? '承認時の候補単価' : '未承認候補'}: {Math.round(proposal.calculation.candidate_yen_per_person_hour).toLocaleString()} 円/人時</strong></p>}
      {proposal.calculation.unknowns.map((item) => <p key={item}>停止理由: {item}</p>)}
      {proposal.calculation.basis.map((row, index) => <p key={`${row.label}-${index}`}>{row.label}: {String(row.value ?? '未確認')} {row.unit}</p>)}
      {proposal.calculation.excluded_items.map((item) => <p key={item.cost_id}>労務原価から除外: {item.label} — {item.excluded_reason ?? '別請求項目'}</p>)}
      {proposal.evidence.length > 0 && <><h3>入力根拠</h3>{proposal.evidence.map((item, index) => <div className="shared-evidence" key={`${item.label}-${index}`}>
        <p><strong>{item.label}</strong>: {String(item.value ?? '未入力')} {item.unit}（状態: {item.status}）</p>
        <p className="shared-muted">出典: {item.source ?? '未入力'}{item.evidence_ref ? ` / 根拠ID: ${item.evidence_ref}` : ''} / 記録: {new Date(item.recorded_at).toLocaleString()}</p>
        {item.notes && <p className="shared-muted">備考: {item.notes}</p>}
      </div>)}</>}
      {proposal.approved_by && <p>承認者: {proposal.approved_by}／理由: {proposal.approval_reason}</p>}
      {proposal.status === 'draft' && proposal.rate_type === 'customer' && proposal.calculation.candidate_yen_per_person_hour != null && <div className="shared-evidence">
        <label>承認開始日<input type="date" value={approval_date} onChange={(event) => set_approval_date(event.target.value)} /></label>
        <label>承認者<input value={approved_by} onChange={(event) => set_approved_by(event.target.value)} /></label>
        <label>承認理由<input value={approval_reason} onChange={(event) => set_approval_reason(event.target.value)} /></label>
        <button type="button" className="shared-refresh" disabled={!approved_by.trim() || !approval_reason.trim()} onClick={() => void approve_saved(proposal.proposal_id)}>この候補を承認</button>
      </div>}
    </article>) : <p className="shared-muted">まだ保存された候補はありません。</p>}
    <h2>承認済み単価の有効期間と根拠</h2>
    {rate_history.length ? rate_history.map((record) => <article className="shared-card" key={record.rate_id}>
      <p><strong>{record.labor_rate.yen_per_person_hour.toLocaleString()} 円/人時</strong></p>
      <p>用途: {record.rate_type === 'internal' ? '内部原価' : '顧客請求'} ／ 範囲: {record.rate_scope}</p>
      <p>有効期間: {record.labor_rate.effective_from} 〜 {record.effective_to ?? (record.labor_rate.effective_from > today ? '開始前（終了日未設定）' : '終了日未設定')}</p>
      <p>承認者: {record.approved_by}／理由: {record.approval_reason}</p>
      <ul>{record.labor_rate.basis.map((row, index) => <li key={`${row.label}-${index}`}>{row.label}: {String(row.value ?? '未確認')} {row.unit}</li>)}</ul>
    </article>) : <p className="shared-muted">人が承認した単価はまだありません。</p>}
  </section>;
}

const strategy_screens: Record<string, ComponentType> = {};
for (const [path, module] of Object.entries(import.meta.glob<{ default: ComponentType }>('./R*.tsx', { eager: true }))) {
  const module_id = path.match(/\/(R\d{2})[^/]*\.tsx$/)?.[1];
  if (module_id) strategy_screens[module_id] = module.default;
}

export default function App() {
  const [modules, set_modules] = useState([{ module_id: 'R15', title: '年間費用から試算', description: '' }]);
  const [selected_module, set_selected_module] = useState('integrated');

  useEffect(() => {
    api.list_modules().then((found) => {
      if (found.length > 0) set_modules(found);
    }).catch(() => {
      // R15 remains available when the local API is still starting.
    });
  }, []);

  const StrategyScreen = strategy_screens[selected_module];
  const integrated_steps = [
    { module_id: 'R13', title: '1. 年度費用を確認' },
    { module_id: 'R16', title: '2. 期間稼働を積算' },
    { module_id: 'R06', title: '3. シナリオ補正' },
    { module_id: 'R30', title: '4. 根拠を点検' },
    { module_id: 'R19', title: '5. 承認済み有効単価' },
  ];
  return <div className="strategy-app">
    <style>{`.strategy-app{min-height:100vh;background:#e8eeeb}.strategy-app input,.strategy-app textarea,.strategy-app select{min-width:0;max-width:100%;box-sizing:border-box}.strategy-app textarea{width:100%}.strategy-app label{min-width:0}.strategy-picker{max-width:760px;margin:0 auto;padding:18px clamp(18px,5vw,42px) 0;background:#f7f8f3}.strategy-picker label{display:grid;gap:7px;font:700 14px/1.4 "Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;color:#213b41}.strategy-picker select{min-height:48px;width:100%;border:1px solid #96aaa4;border-radius:4px;padding:10px 12px;background:#fff;color:#182e35;font:inherit}.strategy-picker :focus-visible{outline:3px solid #df9b33;outline-offset:3px}.integrated-flow{max-width:760px;margin:12px auto 0;padding:12px clamp(18px,5vw,42px);background:#f7f8f3;color:#182e35}.integrated-flow h2{font-size:18px}.integrated-flow p{line-height:1.6}.integrated-steps{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.integrated-steps button{min-height:48px;border:1px solid #17665e;border-radius:5px;background:#fff;color:#17665e;font-weight:700}.integrated-steps button[aria-current=step]{background:#17665e;color:#fff}@media(max-width:430px){.integrated-steps{grid-template-columns:1fr}}`}</style>
    <div className="strategy-picker"><label htmlFor="strategy-select">試算方式<select id="strategy-select" value={selected_module} onChange={event => set_selected_module(event.target.value)}><option value="integrated">統合フォーム</option>{modules.map(module => <option key={module.module_id} value={module.module_id}>{module.title}（{module.module_id}）</option>)}</select></label></div>
    <section className="integrated-flow" aria-label="参考方式への案内">
      <h2>統合フォームと参考方式</h2>
      <p>既定フォームで費用・稼働・根拠を保存して承認します。以下は参考方式への移動で、入力値は自動転送されません。</p>
      <nav className="integrated-steps">{integrated_steps.map((step) => <button key={step.module_id} type="button" aria-current={selected_module === step.module_id ? 'step' : undefined} onClick={() => set_selected_module(step.module_id)}>{step.title}　{step.module_id}</button>)}</nav>
    </section>
    {selected_module === 'integrated' ? <R15Screen /> : StrategyScreen ? <StrategyScreen /> : <p className="strategy-picker">この方式の画面は準備中です。</p>}
    <SharedRecordsPanel />
  </div>;
}
