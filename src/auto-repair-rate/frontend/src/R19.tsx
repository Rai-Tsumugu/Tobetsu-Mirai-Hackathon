import { useState } from 'react';
import type { FormEvent } from 'react';
import type { RateVersion } from './types';
const today = new Date().toISOString().slice(0,10);
const fields: [string, string, string][] = [['年間費用（円）','annual_cost_yen','1200000'], ['年間請求可能人時','annual_billable_hours','600'], ['工場標準として有効にする開始日','valid_from','']];
const fieldRows = fields.map(([label,key,initial]) => ({label,key,initial}));
type Values = Record<string,string>;
export default function R19Screen() {
 const [values,setValues]=useState<Values>(Object.fromEntries(fieldRows.map(f=>[f.key,String(f.initial || '')])));
 const [result,setResult]=useState<any>(null); const [active,setActive]=useState<any>(null); const [saved,setSaved]=useState<RateVersion|null>(null); const [error,setError]=useState(''); const [busy,setBusy]=useState(false);
 function payload() { return { period_start:`${today.slice(0,4)}-01-01`,source_date:today,effective_from:today,source:'架空シミュレータ',evidence_ref:'架空例 R19-2026',evidence_notes:'説明用の架空入力です。',
      annual_cost_yen: values.annual_cost_yen === '' ? null : Number(values.annual_cost_yen),
      annual_billable_hours: values.annual_billable_hours === '' ? null : Number(values.annual_billable_hours),
      valid_from: values.valid_from || today,    }; }
 useState(()=>{fetch(`/api/auto-repair-rate/R19/rates/active?as_of=${today}`).then(r=>r.ok?r.json():null).then(setActive).catch(()=>setActive(null)); return null;});
 async function send(event:FormEvent, save=false) { event.preventDefault();setBusy(true);setError('');try{const res=await fetch(`/api/auto-repair-rate/R19/${save?'proposals':'rates/preview'}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});if(!res.ok)throw new Error(await res.text());const data=await res.json();setResult(data);if(save)setSaved(data as RateVersion);}catch(e){setError(e instanceof Error?e.message:'処理できませんでした');}finally{setBusy(false);} }
 return <main className="rate-module"><style>{`.rate-module{max-width:760px;margin:0 auto;padding:18px clamp(16px,5vw,38px) 30px;background:#f7f8f3;color:#182e35;font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif}.rate-card{background:white;border:1px solid #c7d3cf;border-radius:8px;padding:15px;margin:12px 0}.rate-fields{display:grid;gap:12px}.rate-fields label{display:grid;gap:6px;font-weight:650}.rate-fields input{box-sizing:border-box;width:100%;min-height:46px;padding:10px;border:1px solid #9aada7;border-radius:5px;font:inherit}.rate-module button{min-height:48px;width:100%;border:0;border-radius:5px;background:#17665e;color:white;font:700 15px inherit;margin-top:10px}`}</style>
 <p>R19 · 架空シミュレータ</p><h2>工場標準単価</h2><p>factory_standard/customer の承認済み有効日履歴を表示します。</p>{active&&<section className="rate-card"><strong>指定日現在: {active.labor_rate.yen_per_person_hour.toLocaleString()} 円/人時</strong><p>適用開始: {active.labor_rate.effective_from}</p></section>}{!active&&<p>指定日現在の承認済み工場標準単価はありません。</p>}<form className="rate-card" onSubmit={e=>send(e)}><div className="rate-fields">{fieldRows.map(f=><label key={f.key}>{f.label}<input value={values[f.key]} onChange={e=>setValues({...values,[f.key]:e.target.value})} aria-label={f.label} inputMode={/date/.test(f.key)?'text':'decimal'} /></label>)}</div><button disabled={busy}>サーバーで確認</button></form>
 {error&&<p role="alert">{error}</p>}{result&&<section className="rate-card"><h3>{result.status==='blocked'?'入力待ち・停止':'未承認候補'}</h3>{result.candidate_yen_per_person_hour!=null&&<p><strong>{Math.round(result.candidate_yen_per_person_hour).toLocaleString()} 円/人時</strong></p>}{(result.blockers||[]).map((x:string)=><p key={x}>確認: {x}</p>)}{(result.basis||[]).map((x:any,i:number)=><p key={i}>{x.label}: {String(x.value??'未確認')} {x.unit}</p>)}{!saved&&<button type="button" disabled={busy||result.status==='blocked'} onClick={e=>send(e as any,true)}>候補を保存</button>}</section>}{saved&&<section className="rate-card">保存済み候補: {saved.rate_scope} / {saved.rate_type}。人の明示承認が必要です。</section>}
 </main>;
}
