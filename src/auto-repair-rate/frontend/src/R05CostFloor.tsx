import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';
import type { RateVersion } from './types';

const today = new Date().toISOString().slice(0, 10);
const year_start = `${today.slice(0, 4)}-01-01`;

export default function R05CostFloor() {
  const [cost_yen, set_cost_yen] = useState('5400000');
  const [period_hours, set_period_hours] = useState('1500');
  const [u_period, set_u_period] = useState('0.75');
  const [target_type, set_target_type] = useState<'profit_amount' | 'profit_margin'>('profit_amount');
  const [target_value, set_target_value] = useState('1350000');
  const [cost_evidence, set_cost_evidence] = useState('架空の費用台帳');
  const [target_evidence, set_target_evidence] = useState('架空の経営目標');
  const [materials_yen, set_materials_yen] = useState('300000');
  const [hours_basis, set_hours_basis] = useState('total_person_hours');
  const [job_hours, set_job_hours] = useState({ low: '1', typical: '1.5', high: '2.5' });
  const [job_billable_ratio, set_job_billable_ratio] = useState('0.8');
  const [effective_from, set_effective_from] = useState(today);
  const [version, set_version] = useState<RateVersion | null>(null);
  const [approved_by, set_approved_by] = useState('');
  const [approval_reason, set_approval_reason] = useState('');
  const [error, set_error] = useState('');
  const [busy, set_busy] = useState(false);
  const number_or_null = (value: string) => value.trim() === '' ? null : Number(value);

  async function calculate_rate(event: FormEvent) {
    event.preventDefault(); set_busy(true); set_error(''); set_version(null);
    try {
      const response = await fetch('/api/auto-repair-rate/R05/proposals', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          period_start: year_start, effective_from, period_label: year_start,
          allocable_cost_yen: number_or_null(cost_yen), period_total_person_hours: number_or_null(period_hours),
          u_period: number_or_null(u_period), target_type, target_value: number_or_null(target_value),
          source: 'R05 simulator input', cost_evidence: cost_evidence || null, target_evidence: target_evidence || null,
          materials_yen: number_or_null(materials_yen), hours_basis,
          job_person_hours: Object.values(job_hours).every(value => value.trim() !== '')
            ? { low: Number(job_hours.low), typical: Number(job_hours.typical), high: Number(job_hours.high) } : null,
          job_billable_ratio: hours_basis === 'total_person_hours' ? number_or_null(job_billable_ratio) : null,
        }),
      });
      if (!response.ok) throw new Error(await response.text() || `API error ${response.status}`);
      set_version(await response.json() as RateVersion);
    } catch (e) { set_error(e instanceof Error ? e.message : '計算に失敗しました'); }
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

  return <main className="r05-shell"><style>{`
    .r05-shell{max-width:760px;min-height:100vh;margin:0 auto;padding:24px clamp(18px,5vw,42px) 60px;border-top:9px solid #17665e;background:#f7f8f3;color:#182e35;font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif}
    .r05-shell *{box-sizing:border-box}.r05-shell header{padding:10px 0 20px;border-bottom:1px solid #c7d3cf}.r05-shell h1{font-size:clamp(28px,7vw,40px);line-height:1.25;margin:8px 0}.r05-shell header p:last-child{line-height:1.7;color:#496067}.r05-eyebrow{font-weight:700;color:#17665e;letter-spacing:.07em;font-size:13px}
    .r05-fictional{padding:14px 16px;margin:18px 0;background:#f4ecd9;border-left:5px solid #d99a31;line-height:1.6;font-weight:700}.r05-form{display:grid;gap:15px;margin:22px 0}.r05-shell label{display:grid;gap:7px;font-weight:700;font-size:15px}.r05-shell input,.r05-shell select{width:100%;min-height:49px;border:1px solid #96aaa4;border-radius:4px;padding:10px 12px;background:#fff;color:#182e35;font:inherit}.r05-shell button{width:100%;min-height:52px;padding:12px 16px;background:#17665e;color:white;border:0;border-radius:4px;font:700 16px inherit}.r05-shell button:disabled{opacity:.55}.r05-formula,.r05-job{padding:14px 16px;background:#e6efeb;border-left:4px solid #528679;line-height:1.7}.r05-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.r05-grid label{font-size:13px}.r05-result{padding:20px 0;border-block:3px solid #17665e;margin-top:26px}.r05-result h2{font-size:24px;color:#164f49}.r05-result li{line-height:1.8}.r05-approval{display:grid;gap:14px;border-top:1px dashed #91a49e;margin-top:20px;padding-top:18px}.r05-error{padding:12px;background:#f8e6e3;color:#84281f}.r05-shell :focus-visible{outline:3px solid #df9b33;outline-offset:3px}
    @media(max-width:430px){.r05-shell{padding-top:17px}.r05-grid{grid-template-columns:1fr 1fr}.r05-grid label:last-child{grid-column:1/-1}}
  `}</style>
    <header><p className="r05-eyebrow">R05　原価下限＋目標利益</p><h1>原価を守る<br />目標単価を決める</h1><p>期間原価から原価下限を求め、利益額か利益率のどちらか一方を加えます。保存と承認履歴は共有APIに記録します。</p></header>
    <aside className="r05-fictional">以下はすべて架空デモ値です。実工場の実績・相場ではありません。</aside>
    <form className="r05-form" onSubmit={calculate_rate}>
      <label>期間の配賦原価（円）<input inputMode="numeric" value={cost_yen} onChange={e => set_cost_yen(e.target.value)} /></label>
      <label>原価の根拠・出典<input value={cost_evidence} onChange={e => set_cost_evidence(e.target.value)} placeholder="根拠不明なら空欄" /></label>
      <label>期間の総労働人時<input inputMode="decimal" value={period_hours} onChange={e => set_period_hours(e.target.value)} /></label>
      <label>期間の請求可能割合 u_period<input inputMode="decimal" min="0" max="1" step="0.01" value={u_period} onChange={e => set_u_period(e.target.value)} /></label>
      <label>目標利益の方式<select value={target_type} onChange={e => set_target_type(e.target.value as 'profit_amount' | 'profit_margin')}><option value="profit_amount">期間利益額</option><option value="profit_margin">売上に対する利益率</option></select></label>
      <label>{target_type === 'profit_amount' ? '目標利益額（円/期間）' : '目標利益率（0以上1未満）'}<input inputMode="decimal" min="0" max={target_type === 'profit_margin' ? '0.99' : undefined} step="any" value={target_value} onChange={e => set_target_value(e.target.value)} /></label>
      <label>目標利益の根拠・出典<input value={target_evidence} onChange={e => set_target_evidence(e.target.value)} placeholder="根拠不明なら空欄" /></label>
      <p className="r05-formula"><strong>式（選択した一方式だけを使用）</strong><br />H_period_bill = 期間総労働人時 × u_period<br />原価単価 = 配賦原価 ÷ H_period_bill<br />利益額: 候補 = 原価単価 + 目標利益額 ÷ H_period_bill<br />利益率: 候補 = 原価単価 ÷ (1 − 目標利益率)</p>
      <label>別請求の部品・材料費（円）<input inputMode="numeric" value={materials_yen} onChange={e => set_materials_yen(e.target.value)} /></label>
      <section className="r05-job"><strong>案件の時間は別計算</strong><br />u_period は期間分母だけに使い、案件請求可能割合は案件の総人時にだけ適用します。</section>
      <label>案件の時間基準<select value={hours_basis} onChange={e => set_hours_basis(e.target.value)}><option value="total_person_hours">案件総人時から換算</option><option value="billable_person_hours">請求可能人時を入力済み</option></select></label>
      <div className="r05-grid">{(['low','typical','high'] as const).map(k => <label key={k}>{k === 'low' ? '低' : k === 'typical' ? '標準' : '高'}・案件人時<input inputMode="decimal" value={job_hours[k]} onChange={e => set_job_hours({...job_hours,[k]:e.target.value})} /></label>)}</div>
      {hours_basis === 'total_person_hours' && <label>案件請求可能割合（案件だけに適用）<input inputMode="decimal" min="0" max="1" step="0.01" value={job_billable_ratio} onChange={e => set_job_billable_ratio(e.target.value)} /></label>}
      <label>候補の適用開始日<input type="date" value={effective_from} onChange={e => set_effective_from(e.target.value)} required /></label>
      <button disabled={busy}>{busy ? '処理中…' : '候補を計算して保存'}</button>
    </form>
    {error && <p role="alert" className="r05-error">{error}</p>}
    {version && <section className="r05-result" aria-live="polite"><h2>{version.calculation.candidate_yen_per_person_hour == null ? '候補を出せません' : `候補 ${Math.round(version.calculation.candidate_yen_per_person_hour).toLocaleString()} 円 / 人時`}</h2>
      <p>状態: {version.status === 'blocked' ? '根拠・入力の確認待ち' : version.status === 'approved' ? '承認済み' : '未承認の候補'}</p>
      {version.calculation.unknowns.length > 0 && <p>不足・停止理由: {version.calculation.unknowns.join('、')}</p>}
      {version.calculation.excluded_items.map(item => <p key={item.cost_id}>別請求として除外: {item.label}（{item.amount_yen?.toLocaleString()}円）</p>)}
      <ul>{version.calculation.basis.map((row,i) => <li key={i}>{row.label}: {String(row.value)} {row.unit}</li>)}</ul>
      <p>根拠: {version.evidence.map(item => `${item.label}（${item.status}・${item.source ?? '出典未入力'}）`).join('、')}</p>
      {version.labor_rate && <p><strong>承認後単価: {version.labor_rate.yen_per_person_hour.toLocaleString()} 円/人時</strong></p>}
      {version.status === 'draft' && version.calculation.candidate_yen_per_person_hour != null && <div className="r05-approval"><h3>人による承認</h3><label>承認者<input value={approved_by} onChange={e => set_approved_by(e.target.value)} /></label><label>承認理由<input value={approval_reason} onChange={e => set_approval_reason(e.target.value)} /></label><button type="button" disabled={busy || !approved_by.trim() || !approval_reason.trim()} onClick={approve_rate}>候補を承認して履歴に保存</button></div>}
    </section>}
  </main>;
}
