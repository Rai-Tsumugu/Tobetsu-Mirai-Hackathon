import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Band, bands, band_labels, Quote, WorkflowPreview, WorkflowSnapshot } from './models';
import './style.css';

const yen = (value: unknown) => typeof value === 'number'
  ? new Intl.NumberFormat('ja-JP', { style: 'currency', currency: 'JPY', maximumFractionDigits: 0 }).format(value)
  : '未確認';

async function request<T = any>(path: string, body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) {
    const detail = result?.detail;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail ?? result));
  }
  return result as T;
}

function input_snapshot(quote: Quote | null): any | null {
  if (!quote) return null;
  const meta = quote.metadata as any;
  return meta?.input_snapshot ?? (quote as any).inputs ?? (quote as any).snapshot?.inputs ?? null;
}

function app() {
  const [inputs, set_inputs] = useState<any>(null);
  const [quote, set_quote] = useState<Quote | null>(null);
  const [preview, set_preview] = useState<WorkflowPreview | null>(null);
  const [saved_workflow, set_saved_workflow] = useState<WorkflowSnapshot | null>(null);
  const [error, set_error] = useState('');
  const [busy, set_busy] = useState(false);
  const [loading, set_loading] = useState(true);
  const [selected_band, set_selected_band] = useState<Band | null>(null);
  const [operator, set_operator] = useState('operator-demo-01');
  const [final_amount, set_final_amount] = useState('');
  const [override_reason, set_override_reason] = useState('');
  const [condition_note, set_condition_note] = useState('架空: 現車確認後、追加作業があれば再連絡');
  const [history, set_history] = useState<Quote[]>([]);
  const [jobs, set_jobs] = useState<any[]>([]);
  const [search, set_search] = useState('');
  const [notice, set_notice] = useState('');
  const [step, set_step] = useState(0);
  const [show_comparison_detail, set_show_comparison_detail] = useState(false);
  const [tool_result, set_tool_result] = useState<any>(null);

  const run = async (action: () => Promise<void>) => {
    set_busy(true);
    set_error('');
    try { await action(); }
    catch (cause) { set_error(String(cause instanceof Error ? cause.message : cause)); }
    finally { set_busy(false); }
  };

  const clear_derived = () => {
    set_quote(null);
    set_preview(null);
    set_saved_workflow(null);
    set_selected_band(null);
    set_final_amount('');
    set_override_reason('');
    set_condition_note('');
    set_show_comparison_detail(false);
    set_tool_result(null);
    set_notice('');
    set_step(0);
  };

  const load_initial = async () => {
    set_loading(true);
    set_error('');
    try {
      const [demo, available_jobs, saved] = await Promise.all([
        request<any>('/demo'), request<any[]>('/jobs'), request<Quote[]>('/quotes'),
      ]);
      set_inputs(demo);
      set_jobs(available_jobs);
      set_history(saved);
    } catch (cause) {
      set_error(`初期データを読み込めませんでした。通信状態を確認して再読み込みしてください。 ${String(cause)}`);
    } finally { set_loading(false); }
  };

  useEffect(() => { void load_initial(); }, []);

  const update = (path: string, value: any) => {
    if (!inputs) return;
    const copy = structuredClone(inputs);
    const keys = path.split('.');
    let target = copy;
    keys.slice(0, -1).forEach((key) => { target = target[key]; });
    target[keys[keys.length - 1]] = value;
    if (path === 'labor_rate.yen_per_person_hour' && Array.isArray(copy.labor_rate.basis)) {
      copy.labor_rate.basis = copy.labor_rate.basis.map((entry: any) => ({ ...entry, value, unit: '円/人時' }));
    } else if (path === 'labor_rate.yen_per_person_hour') {
      copy.labor_rate.basis = [{ label: '入力された時間単価', value, unit: '円/人時' }];
    }
    if (quote?.status === 'confirmed') {
      copy.quote_id = quote.quote_id;
      copy.quote_version = quote.quote_version + 1;
      copy.parent_version = quote.quote_version;
    }
    set_inputs(copy);
    clear_derived();
  };

  const calculate = () => run(async () => {
    if (!inputs) throw new Error('入力データがありません');
    // Identity gates precede preview; missing pricing conditions are shown by it.
    for (const step_index of [0, 1]) {
      const form_state = await request<any>('/forms/state', { inputs, step: step_index });
      if (!form_state.can_advance) throw new Error(form_state.issues.map((issue: any) => issue.message).join(' / '));
    }
    const result = await request<WorkflowPreview>('/workflow/preview', { inputs });
    clear_derived();
    set_preview(result);
    set_quote(result.quote);
    set_saved_workflow(null);
    set_selected_band(null);
    set_final_amount('');
    set_override_reason('');
    set_show_comparison_detail(false);
    set_step(1);
    set_notice(result.summary?.text || '3つの条件幅を試算しました。金額と条件を確認してください。');
  });

  const load_workflow = async (confirmed: Quote): Promise<WorkflowSnapshot> => {
    return request<WorkflowSnapshot>(`/workflow/${encodeURIComponent(confirmed.quote_id)}?quote_version=${confirmed.quote_version}`);
  };

  const confirm_quote = () => run(async () => {
    if (!quote || !selected_band || !preview?.can_confirm) throw new Error('確認事項を満たし、条件帯を選んでください');
    const form_state = await request<any>('/forms/state', { inputs, step: 4, quote: { ...quote, selected_band, confirmed_by: operator } });
    if (!form_state.can_advance) throw new Error(form_state.issues.map((issue: any) => issue.message).join(' / '));
    const confirmed = await request<Quote>('/quotes/confirm', {
      inputs, quote_id: quote.quote_id, quote_version: quote.quote_version,
      selected_band: selected_band, confirmed_by: operator,
      final_amount: final_amount === '' ? null : Number(final_amount), override_reason: override_reason,
    });
    set_quote(confirmed);
    set_step(2);
    set_notice(`見積もりを確定しました。確定額 ${yen(confirmed.final_amount)}。帳票snapshotを読み込んでいます。`);
    const workflow = await load_workflow(confirmed);
    set_quote(workflow.quote);
    set_saved_workflow(workflow);
    set_notice(`見積もりを確定しました。帳票snapshotを読み込みました。`);
    set_history(await request<Quote[]>('/quotes'));
  });

  const select_saved = (item: Quote) => void run(async () => {
    const saved_inputs = input_snapshot(item);
    set_inputs(saved_inputs ? structuredClone(saved_inputs) : null);
    set_quote(item);
    set_selected_band(item.selected_band);
    set_final_amount(item.final_amount == null ? '' : String(item.final_amount));
    set_override_reason(item.override_reason ?? '');
    set_preview(null);
    set_saved_workflow(null);
    set_condition_note('');
    set_step(item.status === 'confirmed' ? 2 : 1);
    set_tool_result(null);
    if (item.status === 'confirmed') {
      const workflow = await load_workflow(item);
      set_quote(workflow.quote);
      set_saved_workflow(workflow);
    } else if (saved_inputs) {
      const result = await request<WorkflowPreview>('/workflow/preview', { inputs: saved_inputs });
      result.quote.quote_id = item.quote_id;
      result.quote.quote_version = item.quote_version;
      result.quote.metadata = item.metadata;
      set_quote(result.quote);
      set_preview(result);
    }
    set_notice(saved_inputs
      ? '保存版の見積もりと同じ入力snapshotを表示しています。'
      : '保存版に入力snapshotがないため、今回の入力条件を表示せず見積内容のみ表示しています。');
  });

  const export_workflow = () => {
    if (!saved_workflow) return;
    const blob = new Blob([JSON.stringify(saved_workflow, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `quote-${saved_workflow.quote.quote_id}-v${saved_workflow.quote.quote_version}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const nav = ['入力', '比較', '確定', '説明'];
  const describe_next_action = (value: string) => ({
    select_band: '条件帯を選んで確定へ進んでください',
    resolve_conditions: '未確認条件を解消してください',
    explain_and_record: '見積条件を説明し、必要に応じて伝達記録を残してください',
    review_history: '保存済みの説明・変更履歴を確認してください',
  }[value] ?? '次の手順を確認してください');
  const can_visit = (index: number) => index <= step || (index === 1 && Boolean(preview)) || (index === 2 && quote?.status === 'confirmed') || (index === 3 && Boolean(saved_workflow));
  const summary_text = saved_workflow?.summary?.text ?? preview?.summary?.text;
  const contribution_details = useMemo(() => preview?.band_comparison, [preview]);
  const questions = preview?.questions?.questions ?? [];

  if (loading) return <main className="page"><p role="status">架空データを読み込み中…</p></main>;
  if (!inputs && !quote) return <main className="page"><header className="app-header"><div><p className="eyebrow">AUTO REPAIR / SIMULATOR</p><h1>整備見積 統合版</h1></div></header><div role="alert" className="error">{error || '初期データを読み込めませんでした。'}</div><button className="btn mt-4" disabled={busy} onClick={() => void load_initial()}>初期データを再読み込み</button></main>;

  return <main className="page">
    <header className="app-header">
      <div><p className="eyebrow">AUTO REPAIR / SIMULATOR</p><h1>整備見積 統合版</h1><p className="lead">入力 → 比較 → 確定 → 説明。条件と根拠をつないで保存します。</p></div>
      <span className="fictional-badge">全データは架空・実価格ではありません</span>
    </header>
    <nav className="workflow-nav" aria-label="見積手順">{nav.map((label, index) => <button key={label} type="button" aria-current={step === index ? 'step' : undefined} disabled={!can_visit(index)} className={step === index ? 'nav-step active' : 'nav-step'} onClick={() => set_step(index)}><span>{index + 1}</span>{label}</button>)}</nav>
    {error && <div role="alert" className="error">{error}</div>}
    {notice && <p role="status" className="notice">{notice}</p>}

    <div className="workspace">
      {inputs ? <aside className="input-column">
        <section className="card">
          <div className="section-heading"><div><p className="eyebrow">STEP 01</p><h2>見積条件を入力</h2></div></div>
          <label className="label" htmlFor="job-search">作業名・略称から探す</label>
          <input id="job-search" className="field" value={search} onChange={(event) => {
            const value = event.target.value; set_search(value);
            void request<any[]>(`/jobs?query=${encodeURIComponent(value)}`).then(set_jobs).catch((cause) => set_error(String(cause)));
          }} />
          <div className="preset-list">{jobs.map((job) => <button key={job.job_id} className="btn secondary preset" disabled={busy} onClick={() => void run(async () => {
            const loaded = await request<any>('/presets/load', { preset_id: job.preset_id });
            set_inputs(loaded); clear_derived(); set_notice('作業プリセットを読み込みました。今回の条件を確認してください。');
          })}>{job.name}</button>)}</div>
          <label className="label" htmlFor="vehicle-ref">匿名の車両ID</label><input id="vehicle-ref" className="field" value={inputs.vehicle_ref || 'V-DEMO-01'} onChange={(event) => update('vehicle_ref', event.target.value)} />
          <label className="label top-gap">人時（低い / 標準 / 追加）</label>
          <div className="range-inputs">{bands.map((band) => <label key={band}><span>{band_labels[band]}</span><input aria-label={`${band_labels[band]}の人時`} className="field" type="number" min="0" step="0.1" value={inputs.labor.person_hours[band] ?? ''} onChange={(event) => {
            const copy = structuredClone(inputs); const value = event.target.value === '' ? null : Number(event.target.value);
            copy.labor.person_hours[band] = value;
            if (Array.isArray(copy.labor.breakdown) && copy.labor.breakdown.length === 1) copy.labor.breakdown[0].hours[band] = value;
            if (quote?.status === 'confirmed') { copy.quote_id = quote.quote_id; copy.quote_version = quote.quote_version + 1; copy.parent_version = quote.quote_version; }
            set_inputs(copy); clear_derived();
          }} /></label>)}</div>
          <p className="help">乾燥・部品待ちなどの経過時間は工賃へ加算しません。</p>
          <label className="label top-gap" htmlFor="rate">時間単価（円 / 人時）</label><input id="rate" className="field" type="number" min="0" value={inputs.labor_rate.yen_per_person_hour ?? ''} onChange={(event) => update('labor_rate.yen_per_person_hour', event.target.value === '' ? null : Number(event.target.value))} />
          <div className="policy-box"><strong>架空の調整ルール</strong>
            <label><input type="checkbox" checked={Boolean(inputs.discount)} onChange={(event) => update('discount', event.target.checked ? { scope: 'subtotal', line_ids: [], kind: 'rate', value: 0.1, reason: '架空: デモ割引', approved_by: operator, order: 'before_tax' } : null)} /> 承認した10%値引きを税前に適用</label>
            <label><input type="checkbox" checked={Boolean(inputs.minimum_rule)} onChange={(event) => update('minimum_rule', event.target.checked ? { scope: 'labor', amount: 10000, effective_from: '2026-10-01', approved_by: operator, reason: '架空: 最低工賃のデモ' } : null)} /> 承認した最低工賃10,000円</label>
          </div>
          <button className="btn primary full-width top-gap" disabled={busy} onClick={() => void calculate()}>{busy ? '計算中…' : '条件を確認して金額を比較'}</button>
          <button className="btn secondary full-width top-gap-small" disabled={busy || jobs.length === 0} onClick={() => void run(async () => {
            if (inputs.vehicle_ref !== 'V-DEMO-01') throw new Error('電話概算は登録車両 V-DEMO-01 のみ利用できます。条件別の通常試算をご利用ください。');
            const data = await request<any>('/quotes/quick', { preset_id: jobs[0]?.preset_id, vehicle_ref: 'V-DEMO-01' });
            if (!data.shortcut_available) {
              clear_derived();
              set_inputs(data.inputs);
              set_quote(data.quote);
              set_notice('登録条件がそろっていないため電話概算を停止しました。確認事項を見てください。');
              return;
            }
            for (const step_index of [0, 1, 2]) {
              const form_state = await request<any>('/forms/state', { inputs: data.inputs, step: step_index });
              if (!form_state.can_advance) throw new Error(form_state.issues.map((issue: any) => issue.message).join(' / '));
            }
            const preview_result = await request<WorkflowPreview>('/workflow/preview', { inputs: data.inputs });
            clear_derived();
            set_inputs(data.inputs); set_quote(preview_result.quote); set_preview(preview_result); set_saved_workflow(null); set_selected_band(null); set_final_amount(''); set_override_reason(''); set_step(1);
          })}>登録条件で電話概算</button>
        </section>
      </aside> : <aside className="input-column"><section className="card"><h2>保存版の入力</h2><p className="help">この見積もりには入力snapshotがありません。別の現在条件は読み込まず、保存された金額と根拠を表示しています。</p></section></aside>}

      <section className="main-column">
        {!quote && <section className="card empty-state"><span className="empty-mark">¥</span><h2>条件をそろえて、金額の幅を比較</h2><p>低い・標準・追加の3条件を同じ帯で積み上げ、担当者が確認して確定します。</p></section>}
        {quote && <>
          <section className="card comparison-card">
            <div className="section-heading"><div><p className="eyebrow">STEP 02</p><h2>条件ごとの金額を比較</h2></div><span className={`status-pill ${quote.status === 'confirmed' ? 'confirmed' : ''}`}>{quote.status === 'confirmed' ? '確定済み' : quote.status === 'blocked' ? '確認待ち' : '提案'}</span></div>
            {quote.issues?.map((issue) => <p key={`${issue.path}-${issue.code}`} className="error">{issue.path}: {issue.message}</p>)}
            {summary_text && <div className="summary-callout"><strong>見積の説明</strong><p>{summary_text}</p></div>}
            <div className="band-grid">{bands.map((band) => <button key={band} type="button" aria-pressed={selected_band === band || (quote.status === 'confirmed' && quote.selected_band === band)} disabled={busy || quote.status === 'blocked' || quote.status === 'confirmed' || preview?.can_confirm === false} className={`band-card ${(selected_band === band || (quote.status === 'confirmed' && quote.selected_band === band)) ? 'selected' : ''}`} onClick={() => { set_selected_band(band); set_final_amount(''); set_override_reason(''); set_step(2); }}>
              <span className="band-title">{band_labels[band]}</span><strong className="band-price">{yen(quote.total?.[band])}</strong><span className="band-sub">小計 {yen(quote.subtotal?.[band])}</span><span className="band-sub">税（架空設定） {yen(quote.tax?.[band])}</span>
            </button>)}</div>
            {quote.conditions?.length > 0 && <div className="conditions">{quote.conditions.map((condition, index) => <p key={index}>{condition.text} <span>({condition.status})</span></p>)}</div>}
            {questions.length > 0 && <details className="support-details"><summary>確認が必要な質問 ({questions.length})</summary><ul className="question-list">{questions.map((question, index) => <li key={`${question.field}-${index}`}><strong>{question.prompt}</strong><span>{question.detail}</span><small>{question.field} · {question.status}</small></li>)}</ul></details>}
            {preview && preview.band_comparison != null && <details className="support-details" open={show_comparison_detail} onToggle={(event) => set_show_comparison_detail((event.currentTarget as HTMLDetailsElement).open)}><summary>帯ごとの内訳を詳しく見る</summary><pre>{JSON.stringify(contribution_details, null, 2)}</pre></details>}
            {quote.status !== 'confirmed' && preview?.next_action && <p className="next-action"><strong>次の操作：</strong>{describe_next_action(preview.next_action)}</p>}
          </section>

          <section className="card"><div className="section-heading"><div><p className="eyebrow">根拠</p><h2>工賃・部品・材料の内訳</h2></div></div><div className="table-wrap"><table><thead><tr><th>工程 / 品目</th>{bands.map((band) => <th key={band}>{band_labels[band]}</th>)}</tr></thead><tbody>{quote.lines?.map((line) => <tr key={line.line_id}><th scope="row"><details><summary>{line.description}</summary><p className="line-reason">{line.reason}<br />{line.source_system} / {line.source_ref || '出典未設定'} / {String(line.snapshot?.updated_at || '価格snapshotを保存')}</p></details></th>{bands.map((band) => <td key={band}>{yen(line.amount?.[band])}</td>)}</tr>)}</tbody></table></div><p className="help">販売価格に掛率を重ねません。未確認の数量・単位・価格は0円として扱いません。</p></section>

          {quote.status !== 'confirmed' && <section className="card confirm-card"><div className="section-heading"><div><p className="eyebrow">STEP 03</p><h2>担当者が確認して確定</h2></div></div><div className="form-grid"><label><span className="label">担当者ID</span><input className="field" value={operator} onChange={(event) => set_operator(event.target.value)} /></label><label><span className="label">手動の確定額（任意）</span><input className="field" type="number" min="0" placeholder={selected_band ? String(quote.total[selected_band]) : '先に条件帯を選択'} value={final_amount} onChange={(event) => set_final_amount(event.target.value)} /></label></div><label className="top-gap block"><span className="label">修正理由（手動変更時）</span><input className="field" value={override_reason} onChange={(event) => set_override_reason(event.target.value)} /></label><button className="btn primary top-gap" disabled={busy || !selected_band || quote.status !== 'proposed' || preview?.can_confirm === false || (final_amount !== '' && Number(final_amount) !== quote.total[selected_band] && !override_reason.trim())} onClick={() => void confirm_quote()}>この条件・金額で確定して保存</button>{final_amount !== '' && selected_band && Number(final_amount) !== quote.total[selected_band] && !override_reason.trim() && <p className="help">計算額と異なる金額には修正理由が必要です。</p>}</section>}

          {quote.status === 'confirmed' && <section className="card confirmed-card"><div className="section-heading"><div><p className="eyebrow">STEP 03</p><h2>見積もりを確定しました</h2></div><span className="status-pill confirmed">確定済み</span></div><p>選択条件：{quote.selected_band ? band_labels[quote.selected_band] : '未選択'}</p><strong className="final-price">確定額 {yen(quote.final_amount)}</strong>{saved_workflow?.next_action && <p className="next-action"><strong>次の操作：</strong>{describe_next_action(saved_workflow.next_action)}</p>}</section>}

          {quote.status === 'confirmed' && <section className="card"><div className="section-heading"><div><p className="eyebrow">STEP 04</p><h2>説明・帳票</h2></div></div>{saved_workflow ? <>
            {saved_workflow.summary?.text && <div className="summary-callout"><strong>顧客向け説明</strong><p>{saved_workflow.summary.text}</p></div>}
            <div className="document-actions"><button className="btn secondary" onClick={export_workflow}>確定snapshotをJSONで保存</button><button className="btn secondary" onClick={() => window.print()}>帳票を印刷</button></div>
            <div className="communication-box"><label className="label" htmlFor="condition-note">電話で伝える条件</label><textarea id="condition-note" className="field" rows={2} value={condition_note} onChange={(event) => set_condition_note(event.target.value)} placeholder="伝えた金額の前提条件" /><button className="btn secondary top-gap-small" disabled={busy || !selected_band || !inputs || !condition_note.trim()} onClick={() => void run(async () => { await request('/communications', { quote_id: quote.quote_id, quote_version: quote.quote_version, selected_band: quote.selected_band, condition_note: condition_note, operator, customer_ref: inputs.customer_ref || 'C-DEMO-01', vehicle_ref: inputs.vehicle_ref || 'V-DEMO-01', inputs }); const refreshed = await load_workflow(quote); set_saved_workflow(refreshed); set_notice('伝達額と条件を通信台帳に記録しました。'); })}>電話で伝えた内容を記録</button></div>
            <div className="print-sheet"><div className="document-header"><div><p className="eyebrow">AUTO REPAIR QUOTE</p><h2>整備見積書</h2></div><p>見積ID {quote.quote_id}<br />版 {quote.quote_version}</p></div><div className="document-meta"><span>車両ID {inputs?.vehicle_ref || '未設定'}</span><span>選択条件 {quote.selected_band ? band_labels[quote.selected_band] : '未選択'}</span><span>確定担当 {quote.confirmed_by || operator}</span></div><table><thead><tr><th>内容</th><th>数量</th><th>単位</th><th>金額</th></tr></thead><tbody>{quote.lines?.map((line) => <tr key={line.line_id}><td>{line.description}</td><td>{quote.selected_band ? line.quantity_range?.[quote.selected_band] ?? '—' : '—'}</td><td>{line.unit}</td><td>{yen(quote.selected_band ? line.amount?.[quote.selected_band] : null)}</td></tr>)}</tbody></table><div className="document-total"><p>小計 <strong>{yen(quote.selected_band ? quote.subtotal?.[quote.selected_band] : null)}</strong></p><p>税（架空設定） <strong>{yen(quote.selected_band ? quote.tax?.[quote.selected_band] : null)}</strong></p><p>計算提示額 <strong>{yen((saved_workflow.document as any)?.proposed_amount ?? (quote.selected_band ? quote.total?.[quote.selected_band] : null))}</strong></p>{Number((saved_workflow.document as any)?.amount_adjustment ?? 0) !== 0 && <p>手動調整 <strong>{yen((saved_workflow.document as any).amount_adjustment)}</strong></p>}<p className="grand-total">確定額 <strong>{yen(quote.final_amount)}</strong></p></div>{(saved_workflow.document as any)?.override_reason && <p className="document-note"><strong>手動調整の理由：</strong>{(saved_workflow.document as any).override_reason}</p>}<p className="document-note">{(saved_workflow.document as any)?.tax_allocation_note || '税内訳の適用・配分条件は確認が必要です。'}<br /><strong>架空Simulatorの見積データです。実価格・請求書として利用できません。</strong></p><p className="document-note">{saved_workflow.summary?.text || summary_text || '条件と根拠を確認した上で確定した見積もりです。'}</p></div>
            <details className="support-details"><summary>保存された通信・変更履歴を確認 ({saved_workflow.communications?.length ?? 0}件 / {saved_workflow.changes?.length ?? 0}件)</summary><pre>{JSON.stringify({ communications: saved_workflow.communications, changes: saved_workflow.changes }, null, 2)}</pre></details>
          </> : <p className="help">確定snapshotを読み込み中、または読み込みに失敗しました。再読み込みしてください。</p>}</section>}
        </>}
      </section>
    </div>

    <details className="support-details support-section"><summary>履歴・下書き・追加変更</summary><div className="support-grid">
      <section className="card"><h2>保存した見積もり</h2><div className="support-actions"><button className="btn secondary" disabled={busy || !inputs} onClick={() => void run(async () => set_history(await request<Quote[]>(`/quotes?vehicle_ref=${encodeURIComponent(inputs?.vehicle_ref || 'V-DEMO-01')}`)))}>今回の車両で検索</button><button className="btn secondary" disabled={busy} onClick={() => void run(async () => set_history(await request<Quote[]>('/quotes')))}>すべて表示</button></div>{history.length ? history.map((item) => <div className="history-row" key={`${item.quote_id}-${item.quote_version}`}><button className="history-select" onClick={() => select_saved(item)}>{item.quote_id} / 版 {item.quote_version} / {yen(item.final_amount)}<small>{item.status === 'confirmed' ? '確定版' : '下書き'}</small></button></div>) : <p className="help">確定した見積もりがここに表示されます。</p>}</section>
      <section className="card"><h2>下書き</h2><div className="support-actions"><button className="btn secondary" disabled={busy || !inputs} onClick={() => void run(async () => { await request('/drafts/save', { draft_id: 'D-DEMO-01', inputs, step }); set_notice('下書きを保存しました。'); })}>中断して保存</button><button className="btn secondary" disabled={busy} onClick={() => void run(async () => { const mode = window.confirm('現在価格で再開しますか？ キャンセルで当時価格を選びます。') ? 'current' : 'snapshot'; const draft = await request<any>('/drafts/resume', { draft_id: 'D-DEMO-01', resume_mode: mode }); set_inputs(draft.inputs); clear_derived(); set_step(draft.step || 0); set_notice('下書きを再開しました。価格の採用日を確認してください。'); })}>再開</button></div></section>
      <section className="card"><h2>追加変更</h2><p className="help">確定前提や顧客了承の記録は、見積もり確定後に利用できます。</p>{quote && <div className="support-actions"><button className="btn secondary" disabled={busy || quote.status !== 'confirmed'} onClick={() => void run(async () => { const workflow = await load_workflow(quote); set_saved_workflow(workflow); set_notice('最新の確定snapshotを再読み込みしました。'); })}>確定情報を再読み込み</button><button className="btn secondary" disabled={busy || quote.status !== 'confirmed'} onClick={() => void run(async () => { const result = await request<any>('/quotes/' + quote.quote_id + '/changes'); set_tool_result(result); })}>変更履歴を取得</button><button className="btn secondary" disabled={busy || !quote.parent_version || Number(quote.parent_version) >= quote.quote_version || !inputs} onClick={() => void run(async () => { const result = await request<any>('/changes', { quote_id: quote.quote_id, from_version: Number(quote.parent_version), to_version: quote.quote_version, inputs, trigger_ref: 'OBS-DEMO-01', operator, condition_note: condition_note || '架空: 追加条件の説明を確認中', ack_status: 'pending' }); set_tool_result(result); })}>追加変更を未了承で記録</button></div>}</section>
      <section className="card support-tools"><h2>比較・説明ツール</h2><p className="help">補助機能は必要なときに開いて確認できます。</p>{quote && <div className="support-actions">
        <button className="btn secondary" disabled={busy || !inputs} onClick={() => void run(async () => set_tool_result(await request('/questions', { inputs })))}>不足条件の質問</button>
        <button className="btn secondary" disabled={busy || !selected_band} onClick={() => void run(async () => set_tool_result(await request('/quotes/summary', { quote, selected_band })))}>説明文を生成</button>
        <button className="btn secondary" disabled={busy} onClick={() => void run(async () => set_tool_result(await request('/quotes/compare-bands', { quote })))}>帯の条件差を比較</button>
        <button className="btn secondary" disabled={busy || !inputs?.items?.length} onClick={() => void run(async () => set_tool_result(await request('/prices/compare', { history: inputs.items, item_id: inputs.items[0].item_id })))}>仕入・販売価格を比較</button>
        <button className="btn secondary" disabled={busy || quote.status !== 'confirmed'} onClick={() => void run(async () => set_tool_result(await request(`/quotes/${quote.quote_id}/document?quote_version=${quote.quote_version}`)))}>帳票データを確認</button>
        <button className="btn secondary" disabled={busy || history.length < 2} onClick={() => void run(async () => { const other = history.find((item) => item.quote_id !== quote.quote_id); if (!other) throw new Error('比較する別案件の保存見積が必要です'); set_tool_result(await request('/quotes/combine', { quotes: [quote, other] })); })}>別作業と統合比較</button>
        <button className="btn secondary" disabled={busy || !inputs || quote.status !== 'confirmed'} onClick={() => void run(async () => { const revised = await request<Quote>('/quotes/revise', { quote_id: quote.quote_id, from_version: quote.quote_version, inputs }); const revised_inputs = input_snapshot(revised) ?? inputs; const result = await request<WorkflowPreview>('/workflow/preview', { inputs: revised_inputs }); result.quote.quote_id = revised.quote_id; result.quote.quote_version = revised.quote_version; result.quote.parent_version = revised.parent_version; result.quote.metadata = revised.metadata; set_inputs(revised_inputs); set_quote(result.quote); set_preview(result); set_saved_workflow(null); set_selected_band(null); set_final_amount(''); set_override_reason(''); set_condition_note(''); set_tool_result(null); set_step(1); set_notice('今回条件で次の見積版を準備しました。条件を選び直してください。'); })}>今回条件で新しい版</button>
        <button className="btn secondary" disabled={busy || history.length < 1} onClick={() => void run(async () => { const prior = history.find((item) => item.quote_id === quote.quote_id && item.quote_version < quote.quote_version) ?? history.find((item) => item.quote_id !== quote.quote_id); if (!prior) throw new Error('差分を比較する保存版がありません'); set_tool_result(await request('/quotes/diff', { from_quote: prior, to_quote: quote })); })}>保存版との差分</button>
        <button className="btn secondary" disabled={busy || !quote.parent_version || Number(quote.parent_version) >= quote.quote_version || !inputs} onClick={() => void run(async () => { const records = await request<any[]>(`/quotes/${quote.quote_id}/communications`); const communication = records.filter((record) => record.quote_version === quote.quote_version).at(-1); if (!communication) throw new Error('この見積版の伝達内容を先に記録してください'); set_tool_result(await request('/changes', { quote_id: quote.quote_id, from_version: Number(quote.parent_version), to_version: quote.quote_version, inputs, trigger_ref: 'OBS-DEMO-01', operator, condition_note: communication.condition_note, communicated_amount: communication.communicated_amount, communication_id: communication.communication_id, ack_status: 'accepted' })); })}>顧客了承を記録</button>
      </div>}{tool_result && <pre className="tool-result">{JSON.stringify(tool_result, null, 2)}</pre>}</section>
    </div></details>
  </main>;
}

createRoot(document.getElementById('root')!).render(React.createElement(app));
