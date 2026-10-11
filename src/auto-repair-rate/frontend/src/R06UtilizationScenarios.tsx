import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';
import type { RateVersion } from './types';

const today = new Date().toISOString().slice(0, 10);
const year_start = `${today.slice(0, 4)}-01-01`;
const scenario_labels = { low: '低単価', typical: '標準', high: '高単価' } as const;
type Scenario = keyof typeof scenario_labels;
type ScenarioPreview = {
  available: boolean;
  scenario_rates: Record<Scenario, number | null>;
  scenario_denominators: Record<Scenario, number | null>;
  formulas: Record<Scenario, string>;
  explanations: Record<Scenario, string>;
  blockers: string[];
};

export default function R06UtilizationScenarios() {
  const [cost_yen, set_cost_yen] = useState('7200000');
  const [period_hours, set_period_hours] = useState('1600');
  const [u_period, set_u_period] = useState({ low: '0.65', mid: '0.75', high: '0.85' });
  const [selected_scenario, set_selected_scenario] = useState<Scenario | ''>('');
  const [cost_evidence, set_cost_evidence] = useState('説明用の架空費用例');
  const [scenario_source, set_scenario_source] = useState('架空シミュレータ入力');
  const [scenario_evidence, set_scenario_evidence] = useState('説明用の架空稼働率。実工場の測定値ではありません。');
  const [job_enabled, set_job_enabled] = useState(false);
  const [hours_basis, set_hours_basis] = useState<'total_person_hours' | 'billable_person_hours'>('total_person_hours');
  const [job_hours, set_job_hours] = useState({ low: '', typical: '', high: '' });
  const [job_billable_ratio, set_job_billable_ratio] = useState('');
  const [materials_yen, set_materials_yen] = useState('');
  const [effective_from, set_effective_from] = useState(today);
  const [preview, set_preview] = useState<ScenarioPreview | null>(null);
  const [preview_input, set_preview_input] = useState<Record<string, unknown> | null>(null);
  const [version, set_version] = useState<RateVersion | null>(null);
  const [approved_by, set_approved_by] = useState('');
  const [approval_reason, set_approval_reason] = useState('');
  const [error, set_error] = useState('');
  const [busy, set_busy] = useState(false);
  const number_or_null = (value: string) => value.trim() === '' ? null : Number(value);

  function proposal_payload(scenario: Scenario | null) {
    const job_values = Object.values(job_hours);
    return {
          period_start: year_start, effective_from,
          allocable_cost_yen: number_or_null(cost_yen), period_total_person_hours: number_or_null(period_hours),
          u_period_low: number_or_null(u_period.low), u_period_mid: number_or_null(u_period.mid),
          u_period_high: number_or_null(u_period.high), selected_scenario: scenario,
          source: 'R06 simulator input', scenario_source: scenario_source || null,
          scenario_status: scenario_source === '架空シミュレータ入力' ? 'assumed' : 'entered',
          cost_evidence: cost_evidence || null, scenario_evidence: scenario_evidence || null,
          hours_basis: job_enabled ? hours_basis : null,
          job_person_hours: job_enabled && job_values.every(value => value.trim() !== '')
            ? { low: Number(job_hours.low), typical: Number(job_hours.typical), high: Number(job_hours.high) } : null,
          job_billable_ratio: job_enabled && hours_basis === 'total_person_hours' ? number_or_null(job_billable_ratio) : null,
          materials_yen: number_or_null(materials_yen),
    };
  }

  async function preview_scenarios(event: FormEvent) {
    event.preventDefault(); set_busy(true); set_error(''); set_version(null); set_preview(null); set_preview_input(null); set_selected_scenario('');
    try {
      const input = proposal_payload(null);
      const response = await fetch('/api/auto-repair-rate/R06/scenarios/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      });
      if (!response.ok) throw new Error(await response.text() || `API error ${response.status}`);
      set_preview(await response.json() as ScenarioPreview);
      set_preview_input(input);
    } catch (e) { set_error(e instanceof Error ? e.message : '計算に失敗しました'); }
    finally { set_busy(false); }
  }

  async function save_selected_scenario() {
    if (!selected_scenario || !preview_input) return;
    set_busy(true); set_error('');
    try {
      const response = await fetch('/api/auto-repair-rate/R06/proposals', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...preview_input, selected_scenario }),
      });
      if (!response.ok) throw new Error(await response.text() || `API error ${response.status}`);
      set_version(await response.json() as RateVersion);
    } catch (e) { set_error(e instanceof Error ? e.message : '保存に失敗しました'); }
    finally { set_busy(false); }
  }

  async function approve_rate() {
    if (!version?.calculation.candidate_yen_per_person_hour) return;
    set_busy(true); set_error('');
    try { set_version(await api.approve_proposal(version.proposal_id, {
      approved_yen_per_person_hour: version.calculation.candidate_yen_per_person_hour,
      effective_from, approved_by, approval_reason,
    })); } catch (e) { set_error(e instanceof Error ? e.message : '承認に失敗しました'); }
    finally { set_busy(false); }
  }

  const basis_value = (label: string) => version?.calculation.basis.find(row => row.label === label)?.value ?? null;
  const selected_rate = version?.calculation.candidate_yen_per_person_hour;
  return <main className="r06-shell"><style>{`
    .r06-shell{max-width:780px;min-height:100vh;margin:0 auto;padding:23px clamp(16px,5vw,40px) 56px;border-top:9px solid #17665e;background:#f7f8f3;color:#182e35;font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif}
    .r06-shell *{box-sizing:border-box}.r06-shell header{padding:9px 0 18px;border-bottom:1px solid #c7d3cf}.r06-shell h1{font-size:clamp(28px,7vw,40px);line-height:1.25;margin:7px 0}.r06-shell header p:last-child{line-height:1.65;color:#496067}.r06-eyebrow{font-weight:700;color:#17665e;letter-spacing:.07em;font-size:13px}
    .r06-shell label{display:grid;gap:7px;font-weight:700;font-size:15px}.r06-shell input,.r06-shell select{width:100%;min-height:49px;border:1px solid #96aaa4;border-radius:5px;padding:10px 12px;background:#fff;color:#182e35;font:inherit}.r06-shell button{width:100%;min-height:52px;padding:12px 16px;background:#17665e;color:white;border:0;border-radius:5px;font:700 16px inherit}.r06-shell button:disabled{opacity:.55}.r06-form{display:grid;gap:15px;margin:20px 0}.r06-fictional{padding:13px 15px;margin:16px 0;background:#f4ecd9;border-left:5px solid #d99a31;line-height:1.55;font-weight:700}.r06-ratios,.r06-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.r06-ratios label{font-size:13px}.r06-note{padding:13px 15px;background:#e6efeb;border-left:4px solid #528679;line-height:1.65}.r06-card{padding:14px 12px;background:#fff;border:1px solid #c7d3cf;border-radius:7px;min-width:0}.r06-card.selected{border:2px solid #17665e;background:#edf5f1}.r06-card strong{display:block;font-size:15px}.r06-card output{display:block;margin:10px 0;font-size:clamp(18px,4.5vw,25px);font-weight:800;color:#164f49;overflow-wrap:anywhere}.r06-card small{display:block;line-height:1.45;color:#496067}.r06-result{padding:18px 0;border-block:3px solid #17665e;margin-top:24px}.r06-result h2{font-size:22px;color:#164f49}.r06-approval{display:grid;gap:13px;border-top:1px dashed #91a49e;margin-top:20px;padding-top:18px}.r06-error{padding:12px;background:#f8e6e3;color:#84281f}.r06-shell :focus-visible{outline:3px solid #df9b33;outline-offset:3px}
    @media(max-width:480px){.r06-shell{padding-top:16px}.r06-ratios,.r06-cards{grid-template-columns:1fr}.r06-card{padding:14px 16px}.r06-card output{font-size:25px}}
  `}</style>
    <header><p className="r06-eyebrow">R06　稼働率シナリオ単価</p><h1>期間稼働率で<br />単価の幅を見る</h1><p>期間原価と期間総労働人時を固定し、入力した low / mid / high の稼働率から3候補を比較します。</p></header>
    <aside className="r06-fictional">初期値は説明用の架空シミュレータ値です。実工場の記録や相場ではありません。実値を確認してから保存してください。</aside>
    <form className="r06-form" onSubmit={preview_scenarios}>
      <label>期間配賦原価 C（円）<input inputMode="numeric" value={cost_yen} onChange={e => set_cost_yen(e.target.value)} /></label>
      <label>期間原価の根拠<input value={cost_evidence} onChange={e => set_cost_evidence(e.target.value)} placeholder="確認した資料・出典を記録" /></label>
      <label>期間総労働人時 H_period_total<input inputMode="decimal" value={period_hours} onChange={e => set_period_hours(e.target.value)} /></label>
      <section><strong>期間稼働率 u_period（0より大きく1以下）</strong><div className="r06-ratios">
        {(['low', 'mid', 'high'] as const).map(band => <label key={band}>{band}<input inputMode="decimal" type="number" min="0.01" max="1" step="0.01" value={u_period[band]} onChange={e => set_u_period({ ...u_period, [band]: e.target.value })} /></label>)}
      </div><p className="r06-note">low ≤ mid ≤ high の順で、根拠を確認した割合を入力してください。不明な値は自動生成せず、空欄のままにします。</p></section>
      <label>稼働率の出典<input value={scenario_source} onChange={e => set_scenario_source(e.target.value)} placeholder="勤怠記録、社長申告など" /></label>
      <label>稼働率の根拠<input value={scenario_evidence} onChange={e => set_scenario_evidence(e.target.value)} placeholder="期間・集計方法など" /></label>
      <section className="r06-note"><strong>案件時間は任意・別計算</strong><br />期間分母には u_period だけを使います。案件が総人時なら案件比率を1回だけ適用し、請求可能人時なら比率を重ねません。</section>
      <label><span><input type="checkbox" checked={job_enabled} onChange={e => set_job_enabled(e.target.checked)} style={{width:22,minHeight:22,verticalAlign:'middle',marginRight:8}} />案件人時も記録する</span></label>
      {job_enabled && <><label>案件人時の基準<select value={hours_basis} onChange={e => set_hours_basis(e.target.value as typeof hours_basis)}><option value="total_person_hours">総人時から換算</option><option value="billable_person_hours">請求可能人時を入力済み</option></select></label>
        <div className="r06-ratios">{(['low','typical','high'] as const).map(key => <label key={key}>案件 {key}<input inputMode="decimal" value={job_hours[key]} onChange={e => set_job_hours({...job_hours,[key]:e.target.value})} /></label>)}</div>
        {hours_basis === 'total_person_hours' && <label>案件請求可能割合（案件時間だけに1回適用）<input inputMode="decimal" min="0" max="1" step="0.01" value={job_billable_ratio} onChange={e => set_job_billable_ratio(e.target.value)} /></label>}
      </>}
      <label>別請求の部品・材料費（円、省略可）<input inputMode="numeric" value={materials_yen} onChange={e => set_materials_yen(e.target.value)} placeholder="労務原価には含めず、記録のみ" /></label>
      <label>適用開始日<input type="date" value={effective_from} onChange={e => set_effective_from(e.target.value)} required /></label>
      <p className="r06-note"><strong>算定式</strong><br />低単価 = C ÷ (H_period_total × u_period_high)<br />標準 = C ÷ (H_period_total × u_period_mid)<br />高単価 = C ÷ (H_period_total × u_period_low)</p>
      <button disabled={busy}>{busy ? '比較中…' : '3候補を計算して比較'}</button>
    </form>
    {error && <p role="alert" className="r06-error">{error}</p>}
    {preview && <section className="r06-result" aria-live="polite"><h2>3つの期間シナリオを比較</h2>
      {preview.blockers.map(item => <p key={item}>確認が必要: {item}</p>)}
      <section className="r06-cards">{(['low','typical','high'] as const).map(key => <article className={`r06-card ${selected_scenario === key ? 'selected' : ''}`} key={key}>
        <strong>{scenario_labels[key]}　({key})</strong>
        <output>{preview.scenario_rates[key] == null ? '算定停止' : `${Math.round(preview.scenario_rates[key]!).toLocaleString()} 円/人時`}</output>
        <small>期間分母: {preview.scenario_denominators[key] == null ? '不明' : `${preview.scenario_denominators[key]} 人時`}</small>
        <small>{preview.formulas[key]}</small><small>{preview.explanations[key]}</small>
      </article>)}</section>
      <label>採用するシナリオ<select required value={selected_scenario} onChange={e => set_selected_scenario(e.target.value as Scenario | '')}><option value="">比較後に選択してください</option>{Object.entries(scenario_labels).map(([key,label]) => <option value={key} key={key}>{label}（{key}）</option>)}</select></label>
      <button type="button" disabled={busy || !preview.available || !selected_scenario} onClick={save_selected_scenario}>選択した候補を共有ストアへ保存</button>
    </section>}
    {version && <section className="r06-result" aria-live="polite"><h2>{selected_rate == null ? '候補を確定できません' : `選択候補 ${Math.round(selected_rate).toLocaleString()} 円 / 人時`}</h2>
      <p>状態: {version.status === 'blocked' ? '根拠または入力待ち' : version.status === 'approved' ? '人が承認済み' : '未承認の候補'}　/　選択: {String(basis_value('選択シナリオ') ?? '未選択')}</p>
      {version.calculation.unknowns.map(item => <p key={item}>停止理由: {item}</p>)}
      <p>根拠状態: {String(basis_value('稼働率根拠状態') ?? 'unknown')}　/　出典: {String(basis_value('稼働率出典') ?? '未入力')}</p>
      <p>根拠記録日: {String(basis_value('根拠記録日') ?? '未記録')}　/　適用開始日: {String(basis_value('単価適用開始日') ?? effective_from)}</p>
      {version.calculation.job_billable_person_hours && <p>案件請求人時（低／標準／高）: {version.calculation.job_billable_person_hours.low} ／ {version.calculation.job_billable_person_hours.typical} ／ {version.calculation.job_billable_person_hours.high}</p>}
      {version.calculation.excluded_items.map(item => <p key={item.cost_id}>労務原価から除外: {item.label}（別請求）</p>)}
      {version.labor_rate && <p><strong>承認済み単価: {version.labor_rate.yen_per_person_hour.toLocaleString()} 円/人時（{version.labor_rate.effective_from}〜）</strong></p>}
      {version.status === 'draft' && selected_rate != null && <div className="r06-approval"><h3>人による承認</h3>
        <label>承認者<input value={approved_by} onChange={e => set_approved_by(e.target.value)} /></label>
        <label>承認理由<input value={approval_reason} onChange={e => set_approval_reason(e.target.value)} /></label>
        <button type="button" disabled={busy || !approved_by.trim() || !approval_reason.trim()} onClick={approve_rate}>選択候補を承認して単価履歴へ</button>
      </div>}
    </section>}
  </main>;
}
