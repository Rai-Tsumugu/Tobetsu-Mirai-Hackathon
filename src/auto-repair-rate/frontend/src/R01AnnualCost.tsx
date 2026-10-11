import { useMemo, useState } from "react";

type Cost = {
  id: string; category: string; label: string; amount_yen: number | null;
  included_in_rate: boolean;
  status: "confirmed" | "provided" | "estimated" | "unknown";
  source: string | null; evidence: string | null; payroll_overlap?: boolean;
  payroll_overlap_confirmed?: boolean;
};
type Props = { initial?: {
  period_label: string; period_start: string; period_end: string;
  effective_from: string; annual_allocable_cost_yen: number | null;
  H_period_total: number | null; u_period: number | null;
  hours_basis: "total_person_hours" | "billable_person_hours";
  job_billable_ratio: number | null; costs: Cost[]; fictional?: boolean;
} };

const demo: NonNullable<Props["initial"]> = {
  period_label: "2025年度（架空デモ）", period_start: "2025-01-01",
  period_end: "2025-12-31", effective_from: "2026-01-01",
  annual_allocable_cost_yen: 7200000,
  H_period_total: 1600, u_period: 0.75,
  hours_basis: "total_person_hours", job_billable_ratio: 0.8, fictional: true,
  costs: [
    { id: "wages", category: "labor", label: "人件費", amount_yen: 5200000, included_in_rate: true, status: "confirmed", source: "架空デモ入力", evidence: "給与・会社負担分を含む年間集計の例", payroll_overlap_confirmed: true },
    { id: "rent", category: "facility", label: "工場の家賃", amount_yen: 1200000, included_in_rate: true, status: "confirmed", source: "架空デモ入力", evidence: "年間賃料の例", payroll_overlap_confirmed: true },
    { id: "heating", category: "utilities", label: "暖房費", amount_yen: 800000, included_in_rate: true, status: "estimated", source: "架空デモ入力", evidence: "年間暖房費の仮置き", payroll_overlap_confirmed: true },
    { id: "materials", category: "materials", label: "塗料・消耗材料", amount_yen: 350000, included_in_rate: false, status: "provided", source: "架空デモ入力", evidence: "工賃と別に請求する材料費の例" },
  ],
};
const yen = (amount: number) => new Intl.NumberFormat("ja-JP").format(amount);
const status_label: Record<Cost["status"], string> = { confirmed: "確認済み", provided: "入力済み", estimated: "仮置き", unknown: "不明" };

export default function R01AnnualCost({ initial = demo }: Props) {
  const [costs, set_costs] = useState(initial.costs);
  const [period_start, set_period_start] = useState(initial.period_start);
  const [period_end, set_period_end] = useState(initial.period_end);
  const [effective_from, set_effective_from] = useState(initial.effective_from);
  const [aggregate, set_aggregate] = useState(initial.annual_allocable_cost_yen?.toString() ?? "");
  const [hours, set_hours] = useState(initial.H_period_total?.toString() ?? "");
  const [job_person_hours, set_job_person_hours] = useState("2.5");
  const [utilization, set_utilization] = useState(initial.u_period?.toString() ?? "");
  const [basis, set_basis] = useState(initial.hours_basis);
  const [job_ratio, set_job_ratio] = useState(initial.job_billable_ratio?.toString() ?? "");
  const [preview_requested, set_preview_requested] = useState(false);
  const [busy, set_busy] = useState(false);
  const [message, set_message] = useState("");
  const [version, set_version] = useState<{proposal_id: string; status: string; calculation: { candidate_yen_per_person_hour: number | null; denominator_person_hours: number | null; unknowns: string[] }; labor_rate: { yen_per_person_hour: number } | null} | null>(null);
  const [candidate_effective_from, set_candidate_effective_from] = useState<string | null>(null);
  const [approved_by, set_approved_by] = useState("");
  const [approval_reason, set_approval_reason] = useState("");

  const calculation = useMemo(() => {
    const blockers: string[] = [];
    let allocable_cost = 0;
    for (const cost of costs) {
      if (!cost.included_in_rate) continue;
      if (cost.amount_yen === null || cost.status === "unknown") blockers.push(`${cost.label}の金額が不明です`);
      else if (!Number.isFinite(cost.amount_yen) || !Number.isInteger(cost.amount_yen) || cost.amount_yen < 0) blockers.push(`${cost.label}は整数の円で入力してください`);
      else allocable_cost += cost.amount_yen;
      if (!cost.source || !cost.evidence) blockers.push(`${cost.label}の出典と根拠を入力してください`);
      if (cost.payroll_overlap) blockers.push(`${cost.label}は人件費との重複を確認してください`);
      if (cost.payroll_overlap_confirmed !== true) blockers.push(`${cost.label}は人件費との重複がないことを確認してください`);
      if (cost.category === "parts" || cost.category === "materials") blockers.push(`${cost.label}は工賃原価に含められません`);
    }
    const aggregate_amount = aggregate === "" ? null : Number(aggregate);
    if (aggregate_amount === null || !Number.isFinite(aggregate_amount) || !Number.isInteger(aggregate_amount) || aggregate_amount < 0) blockers.push("年間配賦費用は整数の円で入力してください");
    else if (aggregate_amount !== allocable_cost) blockers.push("年間配賦費用の合計と費目明細が一致しません");
    const total_hours = Number(hours), period_use = Number(utilization);
    if (!hours || !Number.isFinite(total_hours) || total_hours <= 0) blockers.push("年間総労働人時を0より大きく入力してください");
    if (!utilization || !Number.isFinite(period_use) || period_use <= 0 || period_use > 1) blockers.push("請求可能割合は0より大きく1以下で入力してください");
    const billable_hours = total_hours > 0 && period_use > 0 && period_use <= 1 ? total_hours * period_use : null;
    if (billable_hours === 0) blockers.push("請求可能人時が0のため試算できません");
    const entered_job_hours = job_person_hours === "" ? NaN : Number(job_person_hours);
    const job_hours = !Number.isFinite(entered_job_hours) || entered_job_hours < 0 ? null
      : basis === "billable_person_hours" ? entered_job_hours
        : job_ratio !== "" && Number(job_ratio) >= 0 && Number(job_ratio) <= 1 ? entered_job_hours * Number(job_ratio) : null;
    if (!period_start || !period_end || !effective_from) blockers.push("対象期間と適用開始日を入力してください");
    return { allocable_cost, aggregate_amount, billable_hours, blockers, job_hours };
  }, [costs, aggregate, hours, utilization, basis, job_ratio, period_start, period_end, effective_from]);

  async function create_candidate() {
    set_preview_requested(true);
    set_message("");
    set_version(null);
    set_candidate_effective_from(null);
    set_busy(true);
    const status: Record<Cost["status"], string> = { confirmed: "factory_reported", provided: "entered", estimated: "assumed", unknown: "unknown" };
    const api_base = (import.meta as ImportMeta & { env?: { VITE_API_BASE?: string } }).env?.VITE_API_BASE ?? "";
    try {
      const response = await fetch(`${api_base}/api/auto-repair-rate/R01/proposals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proposal: {
          module_id: "R01", period_start, period_end, effective_from,
          allocable_cost_yen: calculation.aggregate_amount,
          period_total_person_hours: Number(hours), u_period: Number(utilization),
          hours_basis: basis, job_person_hours: job_person_hours === "" ? null : { low: Number(job_person_hours), typical: Number(job_person_hours), high: Number(job_person_hours) },
          job_billable_ratio: basis === "total_person_hours" && job_ratio !== "" ? Number(job_ratio) : null,
          costs: costs.map((cost) => ({
            cost_id: cost.id, label: cost.label, amount_yen: cost.amount_yen, period: `${period_start}/${period_end}`,
            source: cost.source, evidence_status: status[cost.status],
            billing_class: cost.included_in_rate ? "labor_pool" : "separately_billed_item",
            included_in_labor_pool: cost.included_in_rate,
            excluded_reason: cost.included_in_rate ? null : "工賃と別請求する材料費",
          })),
          evidence: costs.map((cost) => ({
            label: cost.label, value: cost.amount_yen, unit: "円/年", status: status[cost.status],
            source: cost.source, evidence_ref: null, recorded_at: new Date().toISOString(),
            notes: cost.evidence,
          })),
          source: "fictional_simulator", notes: "架空デモ値。実データではありません。",
        }, payroll_overlap_cost_ids: costs.filter((cost) => cost.payroll_overlap).map((cost) => cost.id),
        payroll_overlap_unconfirmed_cost_ids: costs.filter((cost) => cost.included_in_rate && cost.payroll_overlap_confirmed !== true).map((cost) => cost.id),
        cost_evidence_by_id: Object.fromEntries(costs.map((cost) => [cost.id, cost.evidence ?? ""])) }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body));
      set_candidate_effective_from(effective_from);
      set_version(body);
    } catch (error) {
      set_message(error instanceof Error ? error.message : "候補を保存できませんでした");
    } finally {
      set_busy(false);
    }
  }

  async function approve_candidate() {
    if (!version || !approved_by.trim() || !approval_reason.trim()) return;
    set_busy(true);
    set_message("");
    const api_base = (import.meta as ImportMeta & { env?: { VITE_API_BASE?: string } }).env?.VITE_API_BASE ?? "";
    try {
      const response = await fetch(`${api_base}/api/auto-repair-rate/proposals/${encodeURIComponent(version.proposal_id)}/approval`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved_yen_per_person_hour: version.calculation.candidate_yen_per_person_hour, effective_from: candidate_effective_from ?? effective_from, approved_by: approved_by, approval_reason: approval_reason }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body));
      set_version(body);
    } catch (error) {
      set_message(error instanceof Error ? error.message : "承認を保存できませんでした");
    } finally {
      set_busy(false);
    }
  }

  function reset_preview() {
    set_version(null);
    set_candidate_effective_from(null);
    set_preview_requested(false);
  }

  function update_amount(id: string, value: string) {
    set_costs((current) => current.map((cost) => cost.id === id
      ? { ...cost, amount_yen: value === "" ? null : Number(value), status: value === "" ? "unknown" : "provided" }
      : cost));
  }

  function update_cost_text(id: string, field: "source" | "evidence", value: string) {
    set_costs((current) => current.map((cost) => cost.id === id ? { ...cost, [field]: value } : cost));
  }

  function confirm_payroll_review(id: string, checked: boolean) {
    set_costs((current) => current.map((cost) => cost.id === id ? { ...cost, payroll_overlap_confirmed: checked } : cost));
  }

  return (
    <main className="r01-shell">
      <style>{`
        .r01-shell{--ink:#263b3b;--muted:#5d7170;--paper:#f3f6f2;--panel:#fff;--line:#c9d6d0;--pine:#17675b;color:var(--ink);background:var(--paper);font-family:ui-sans-serif,system-ui,-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;max-width:760px;margin:auto;padding:clamp(16px,4vw,34px);line-height:1.5}
        .r01-shell *{box-sizing:border-box}.r01-shell h1,.r01-shell h2,.r01-shell p{margin-top:0}.r01-shell h1{font-size:clamp(1.8rem,7vw,2.8rem);line-height:1.12;letter-spacing:-.04em;max-width:12ch;margin-bottom:12px}.r01-intro{color:var(--muted);max-width:58ch;margin-bottom:22px}
        .r01-fiction{display:inline-flex;background:#f5e8c7;color:#5b4418;padding:5px 10px;border-radius:4px;font-size:.82rem;font-weight:700;margin-bottom:18px}
        .r01-cost-list{display:grid;gap:10px;margin:12px 0 25px}.r01-cost{display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,240px);gap:8px 18px;padding:15px 16px;background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--pine);border-radius:5px}.r01-cost.is-excluded{border-left-color:#839391;background:#f9faf8}.r01-cost h3{font-size:1rem;margin:0}.r01-cost p{font-size:.83rem;color:var(--muted);margin:4px 0 0}.r01-cost-controls{grid-column:2;grid-row:1 / span 3;display:grid;gap:7px}.r01-cost label{color:var(--muted);font-size:.76rem}.r01-cost input,.r01-field input,.r01-field select{width:100%;margin-top:5px;padding:10px 11px;border:1px solid #8ca19a;border-radius:4px;background:white;color:var(--ink);font:inherit}.r01-cost input{text-align:right;font-variant-numeric:tabular-nums}.r01-cost input[type=checkbox]{width:auto;margin:0 6px 0 0}.r01-state{font-size:.75rem;color:var(--muted);font-weight:600}.r01-exclusion{grid-column:1/-1;font-size:.8rem;color:#4c625d;padding-top:8px;border-top:1px dashed var(--line)}
        .r01-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}.r01-field{padding:14px;background:#e8efeb;border-radius:5px}.r01-field label{font-weight:650}.r01-field small{display:block;color:var(--muted);margin-top:5px}.r01-section-title{font-size:1.2rem;margin:26px 0 8px}.r01-helper{color:var(--muted);font-size:.9rem}.r01-job{margin:17px 0;padding:14px 16px;border-left:3px solid #9baea8;background:#e9efec;border-radius:0 5px 5px 0}.r01-job strong{display:block}.r01-job p{font-size:.85rem;color:#526864;margin:4px 0 0}
        .r01-actions{display:flex;gap:10px;align-items:center;margin:20px 0}.r01-button{border:0;border-radius:4px;padding:13px 18px;background:var(--pine);color:white;font:inherit;font-weight:700;cursor:pointer}.r01-button.secondary{background:transparent;color:var(--pine);border:1px solid var(--pine)}.r01-button:disabled{opacity:.5;cursor:not-allowed}.r01-result{padding:20px;background:var(--ink);color:#f4f7f4;border-radius:7px}.r01-result h2{font-size:1rem;color:#c9dfd8;margin:0 0 5px}.r01-result .r01-rate{font-size:clamp(2rem,8vw,3.4rem);font-weight:750;line-height:1.1;font-variant-numeric:tabular-nums}.r01-result p{margin:8px 0 0;color:#d2e0dc;font-size:.9rem}.r01-blockers{background:#fff0e8;border:1px solid #d59b77;color:#6a351d;padding:12px 16px;border-radius:4px}.r01-blockers ul{margin:6px 0 0;padding-left:20px}.r01-pending{margin-top:13px;padding:11px 13px;background:#31504c;border-radius:4px;color:#e2eeea;font-size:.88rem}.r01-shell :focus-visible{outline:3px solid #bd8c36;outline-offset:3px}
        @media(max-width:540px){.r01-fields{grid-template-columns:1fr}.r01-cost{grid-template-columns:1fr;padding:13px 12px;gap:6px 11px}.r01-cost-controls{grid-column:1;grid-row:auto}.r01-cost label{font-size:.76rem}.r01-actions{align-items:stretch;flex-direction:column}.r01-button{width:100%}}
        @media(prefers-reduced-motion:reduce){.r01-shell *{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
      `}</style>
      <div className="r01-fiction">架空デモ値 · 実際の工場データではありません</div>
      <h1>一年分の費用から、人時単価を試算</h1>
      <p className="r01-intro">工賃でまかなう費用だけを積み上げ、年間の請求可能人時で割ります。入力した根拠を確認してから、候補を作成します。</p>
      <section aria-labelledby="r01-period-heading">
        <h2 id="r01-period-heading" className="r01-section-title">対象期間と適用開始日</h2>
        <div className="r01-fields">
          <div className="r01-field"><label htmlFor="r01-period-start">対象期間の開始日</label><input id="r01-period-start" type="date" disabled={Boolean(version)} value={period_start} onChange={(event) => set_period_start(event.target.value)} /></div>
          <div className="r01-field"><label htmlFor="r01-period-end">対象期間の終了日</label><input id="r01-period-end" type="date" disabled={Boolean(version)} value={period_end} onChange={(event) => set_period_end(event.target.value)} /></div>
          <div className="r01-field"><label htmlFor="r01-effective-from">候補の適用開始日</label><input id="r01-effective-from" type="date" disabled={Boolean(version)} value={effective_from} onChange={(event) => set_effective_from(event.target.value)} /></div>
        </div>
      </section>

      <section aria-labelledby="r01-cost-heading">
        <h2 id="r01-cost-heading" className="r01-section-title">工賃に配賦する費用</h2>
        <p className="r01-helper">給与を費目ごとに分けた場合など、同じ人件費を重ねて含めていないか各行で確認してください。</p>
        <div className="r01-field"><label htmlFor="r01-cost-total">年間配賦費用の合計</label><input id="r01-cost-total" type="number" min="0" step="1" disabled={Boolean(version)} value={aggregate} onChange={(event) => set_aggregate(event.target.value)} /><small>計上費目の合計と一致していることを確認します。</small></div>
        <div className="r01-cost-list">{costs.map((cost) => (
          <article className={`r01-cost${cost.included_in_rate ? "" : " is-excluded"}`} key={cost.id}>
            <div><h3>{cost.label} <span className="r01-state">{status_label[cost.status]}</span></h3><p>{cost.included_in_rate ? "工賃で回収する費用" : "工賃とは別に請求"}</p></div>
            <div className="r01-cost-controls">
              <label>年間金額（円）<input aria-label={`${cost.label}の年間金額（円）`} type="number" min="0" step="1" disabled={Boolean(version)} value={cost.amount_yen ?? ""} onChange={(event) => update_amount(cost.id, event.target.value)} /></label>
              <label>出典<input disabled={Boolean(version)} value={cost.source ?? ""} onChange={(event) => update_cost_text(cost.id, "source", event.target.value)} placeholder="例：年間集計表" /></label>
              <label>根拠<input disabled={Boolean(version)} value={cost.evidence ?? ""} onChange={(event) => update_cost_text(cost.id, "evidence", event.target.value)} placeholder="金額を確認した資料や説明" /></label>
              {cost.included_in_rate && <label><input type="checkbox" disabled={Boolean(version)} checked={cost.payroll_overlap_confirmed === true} onChange={(event) => confirm_payroll_review(cost.id, event.target.checked)} />ほかの費目と人件費が重複しないことを確認</label>}
            </div>
            {!cost.included_in_rate && <div className="r01-exclusion">工賃と別請求の材料費として、原価合計から除外しています。記録は残ります。</div>}
          </article>
        ))}</div>
      </section>

      <section aria-labelledby="r01-hours-heading">
        <h2 id="r01-hours-heading" className="r01-section-title">年間の働ける時間</h2>
        <div className="r01-fields">
          <div className="r01-field"><label htmlFor="r01-period-hours">年間総労働人時</label><input id="r01-period-hours" type="number" min="0" step="1" disabled={Boolean(version)} value={hours} onChange={(event) => set_hours(event.target.value)} /><small>人 × 時間を合計した値</small></div>
          <div className="r01-field"><label htmlFor="r01-utilization">請求可能割合 u_period</label><input id="r01-utilization" type="number" min="0" max="1" step="0.01" disabled={Boolean(version)} value={utilization} onChange={(event) => set_utilization(event.target.value)} /><small>0より大きく1以下。年間分母に一度だけ適用します。</small></div>
        </div>
        <div className="r01-job"><strong>案件の人時区分（年間分母とは別の扱い）</strong>
          <div className="r01-fields"><div className="r01-field"><label htmlFor="r01-job-hours">案件の作業人時</label><input id="r01-job-hours" type="number" min="0" step="0.1" disabled={Boolean(version)} value={job_person_hours} onChange={(event) => set_job_person_hours(event.target.value)} /></div><div className="r01-field"><label htmlFor="r01-hours-basis">入力する人時</label><select id="r01-hours-basis" disabled={Boolean(version)} value={basis} onChange={(event) => set_basis(event.target.value as typeof basis)}><option value="total_person_hours">総作業人時</option><option value="billable_person_hours">請求可能人時</option></select></div>
            {basis === "total_person_hours" && <div className="r01-field"><label htmlFor="r01-job-ratio">案件の請求可能割合</label><input id="r01-job-ratio" type="number" min="0" max="1" step="0.01" disabled={Boolean(version)} value={job_ratio} onChange={(event) => set_job_ratio(event.target.value)} /></div>}</div>
          <p>総作業人時なら案件割合を一度だけ掛け、請求可能人時ならそのまま扱います。この値は年間分母の u_period に重ねません。表示例：{calculation.job_hours === null ? "割合を入力してください" : `${calculation.job_hours.toLocaleString("ja-JP")} 人時`}</p>
        </div>
      </section>

      <div className="r01-actions"><button className="r01-button" type="button" disabled={busy || Boolean(version)} onClick={create_candidate}>{busy ? "保存中…" : "候補単価を試算"}</button><span className="r01-helper">候補の作成だけでは単価は確定しません。</span></div>
      {message && <p className="r01-blockers" role="alert">{message}</p>}
      {preview_requested && <section className="r01-result" aria-live="polite" aria-labelledby="r01-preview-heading">
        <h2 id="r01-preview-heading">候補の試算 · 人の承認待ち</h2><div className="r01-rate">{version?.calculation.candidate_yen_per_person_hour == null ? "—" : `約 ${yen(Math.round(version.calculation.candidate_yen_per_person_hour))} 円`}</div>
        <p>年間原価 {calculation.blockers.length ? "未確定" : `${yen(calculation.allocable_cost)} 円`} ÷（総労働人時 {hours || "不明"} × 請求可能割合 {utilization || "不明"}）</p><p>請求可能人時：{calculation.billable_hours === null ? "不明" : yen(calculation.billable_hours)} 人時</p>
        {calculation.blockers.length > 0 ? (
          <div className="r01-blockers" role="alert"><strong>不足を確認してください</strong><ul>{calculation.blockers.map((item) => <li key={item}>{item}</li>)}</ul></div>
        ) : version ? (
          <>
            <div className="r01-pending">{version.status === "approved" ? "人の承認を保存しました。" : version.status === "blocked" ? "入力不足のため、単価候補は停止しています。" : "候補を共通APIに保存しました。承認されるまで適用単価は発行されません。"}</div>
            {version.calculation.unknowns.length > 0 && <p>確認事項：{version.calculation.unknowns.join("、")}</p>}
            {version.labor_rate ? (
              <p role="status">承認済み適用単価：{yen(version.labor_rate.yen_per_person_hour)} 円/人時</p>
            ) : version.calculation.candidate_yen_per_person_hour !== null ? (
              <div className="r01-approval">
                <h3>社長による承認</h3>
                <label>承認者<input value={approved_by} onChange={(event) => set_approved_by(event.target.value)} /></label>
                <label>承認理由<input value={approval_reason} onChange={(event) => set_approval_reason(event.target.value)} /></label>
                <button className="r01-button secondary" type="button" disabled={busy || !approved_by.trim() || !approval_reason.trim()} onClick={approve_candidate}>承認して単価を発行</button>
              </div>
            ) : null}
            <button className="r01-button secondary" type="button" disabled={busy} onClick={reset_preview}>入力を変更して新しい候補を作る</button>
          </>
        ) : <p>サーバーで候補を計算・保存しています。</p>}
      </section>}
    </main>
  );
}
