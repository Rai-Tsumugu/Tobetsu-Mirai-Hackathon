"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { Obj } from "@/lib/systems/man-hours/python-compat";

const BANDS = ["low", "typical", "high"] as const;

type Estimate = {
  source: "database" | "json";
  fallback_reason: string | null;
  adopted_rate_table: string;
  result: Obj;
};

type ApiError = { message?: string };

async function post(path: string, body: unknown): Promise<{ ok: boolean; data: Obj }> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await response.json().catch(() => ({ message: "サーバーの応答を読めませんでした" }))) as Obj;
  return { ok: response.ok, data };
}

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "はい" : "いいえ";
  return String(value);
}

function Bands({ values }: { values: Obj }) {
  return (
    <>
      {BANDS.map((band) => (
        <td className="num" key={band}>
          {show(values?.[band])}
        </td>
      ))}
    </>
  );
}

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="mh-scroll">
      <table>
        <thead>
          <tr>
            {head.map((text) => (
              <th key={text}>{text}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="mh-section">
      <h2>{title}</h2>
      {note ? <p className="mh-note">{note}</p> : null}
      {children}
    </section>
  );
}

export default function ManHoursApp({ initialCase }: { initialCase: string }) {
  const [text, setText] = useState(initialCase);
  const [data, setData] = useState<Estimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [approver, setApprover] = useState("mechanic-demo-01");

  function parse(): Obj | null {
    try {
      return JSON.parse(text) as Obj;
    } catch {
      setError("入力が JSON として読めません。カンマや括弧、引用符を確認してください");
      return null;
    }
  }

  async function calculate(source = text) {
    let caseData: Obj;
    try {
      caseData = JSON.parse(source) as Obj;
    } catch {
      setError("入力が JSON として読めません。カンマや括弧、引用符を確認してください");
      return;
    }
    setBusy(true);
    setError(null);
    const { ok, data: body } = await post("/api/man-hours/estimate", { case: caseData });
    setBusy(false);
    if (!ok) {
      setError((body as ApiError).message ?? "計算できませんでした");
      return;
    }
    setData(body as unknown as Estimate);
  }

  useEffect(() => {
    let cancelled = false;
    post("/api/man-hours/estimate", { case: JSON.parse(initialCase) }).then(({ ok, data: body }) => {
      if (cancelled) return;
      if (ok) setData(body as unknown as Estimate);
      else setError((body as ApiError).message ?? "計算できませんでした");
    });
    return () => {
      cancelled = true;
    };
  }, [initialCase]);

  async function save() {
    const caseData = parse();
    if (!caseData) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    const { ok, data: body } = await post("/api/man-hours/estimates", { case: caseData, createdBy: approver });
    setBusy(false);
    if (!ok) {
      setError((body as ApiError).message ?? "保存できませんでした");
      return;
    }
    setMessage(`保存しました（結果 ID: ${body.estimate_id}）。保存は追記で、計算し直すと新しい行になります`);
  }

  async function approve(rateTable: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    const { ok, data: body } = await post("/api/man-hours/rate-tables/approve", { rateTable, approvedBy: approver });
    if (!ok) {
      setBusy(false);
      setError((body as ApiError).message ?? "承認できませんでした");
      return;
    }
    setMessage(
      `補正表 ${body.adopted} を採用しました${body.created ? "（実績から候補を作成）" : ""}。採用版で再計算しています`,
    );
    setBusy(false);
    await calculate();
  }

  const result = data?.result;
  const adopted = data?.adopted_rate_table;
  const databaseReady = data?.source === "database";

  return (
    <div className="mh-body">
      <Section title="入力（今回の車両と入庫時の観察）" note="JSON を編集して「計算する」で再計算できます。">
        <textarea
          aria-label="入力 JSON"
          className="mh-input"
          spellCheck={false}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <div className="mh-actions">
          <button type="button" disabled={busy} onClick={() => calculate()}>
            計算する
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => setText(initialCase)}>
            例の入力に戻す
          </button>
          <button type="button" className="secondary" disabled={busy || !databaseReady} onClick={save}>
            入力と結果を保存
          </button>
        </div>
        {data ? (
          <p className="mh-note">
            データの取得元: {databaseReady ? "DB（現行の工場パラメータ・採用中の補正表・実績）" : "同梱の JSON"}
            {data.fallback_reason ? `（${data.fallback_reason}）` : ""}。採用中の補正表: {adopted}
          </p>
        ) : null}
        {error ? (
          <p className="mh-error" role="alert">
            {error}
          </p>
        ) : null}
        {message ? (
          <p className="mh-ok" role="status">
            {message}
          </p>
        ) : null}
      </Section>

      {result ? <Result result={result} databaseReady={databaseReady} adopted={adopted ?? ""} busy={busy} approver={approver} setApprover={setApprover} approve={approve} /> : null}
    </div>
  );
}

function Result({
  result,
  databaseReady,
  adopted,
  busy,
  approver,
  setApprover,
  approve,
}: {
  result: Obj;
  databaseReady: boolean;
  adopted: string;
  busy: boolean;
  approver: string;
  setApprover: (value: string) => void;
  approve: (rateTable: string) => void;
}) {
  const est = result.estimate;
  const b = result.method_comparison.b;
  const checks = result.checks;
  return (
    <>
      <Section title={`見積もり結果 ${result.case_id}`} note={result.status}>
        <p>
          車両: 初度登録 {result.vehicle.first_registration}（{result.vehicle.elapsed_years}年）、{result.vehicle.odometer_km}km、
          {result.vehicle.season}
        </p>
        <p>
          基準: {result.base.gross_hours} 人時 → 重複控除後 {result.base.base_hours} 人時（基準 {result.base.catalog_version}）
        </p>
        <Table head={["区分", "low", "typical", "high"]}>
          <tr>
            <th scope="row">人時（{est.method}）</th>
            <Bands values={est.labor_hours} />
          </tr>
          <tr>
            <th scope="row">請求人時（請求しない工程を除く）</th>
            <Bands values={est.billed_hours} />
          </tr>
          <tr>
            <th scope="row">経過時間（待機を含む）</th>
            <Bands values={est.elapsed_hours} />
          </tr>
          <tr>
            <th scope="row">
              人時（{b.method}、{b.n}件）
            </th>
            <Bands values={b.labor_hours} />
          </tr>
          <tr>
            <th scope="row">工賃（円）</th>
            <Bands values={result.money.labor_yen} />
          </tr>
          <tr>
            <th scope="row">材料費（円）</th>
            <Bands values={result.money.materials_yen} />
          </tr>
        </Table>
        <p className="mh-note">{est.note}</p>
      </Section>

      <Section title="方式A/C と方式B の比較" note={result.method_comparison.note}>
        <Table head={["方式", "low", "typical", "high"]}>
          <tr>
            <th scope="row">A/C: 基準＋状態に応じた工程の積み上げ</th>
            <Bands values={result.method_comparison.a_c.labor_hours} />
          </tr>
          <tr>
            <th scope="row">
              B: 類似実績の参照（{b.n}件{b.enough_records ? "" : "・件数不足のため参考"}）
            </th>
            <Bands values={b.labor_hours} />
          </tr>
        </Table>
        <p className="mh-note">{b.note}</p>
        <Table head={["実績", "実績人時", "採用", "ブレーキ周りの錆", "経過年数帯", "季節"]}>
          {[...b.cases, ...b.same_vehicle_cases.map((row: Obj) => ({ ...row, same: true }))].map((row: Obj) => (
            <tr key={row.id}>
              <th scope="row">{row.id}</th>
              <td className="num">{row.actual}</td>
              <td>{row.same ? "同一車両のため別掲" : row.adopted ? "採用" : `除外（${row.excluded_by.join("・")}）`}</td>
              <td>{row.conditions.brake_rust?.result ?? "—"}</td>
              <td>{row.conditions.age_band?.result ?? "—"}</td>
              <td>{row.conditions.season?.result ?? "—"}</td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section title="内訳（現車の状態から展開した工程）">
        <Table head={["項目", "状態", "low", "typical", "high", "案"]}>
          {result.items.map((item: Obj) => (
            <tr key={item.id}>
              <th scope="row">{item.label}</th>
              <td>{item.state}</td>
              <Bands values={item.hours} />
              <td>{show(item.from)}</td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section title="確認リスト" note="未確認の項目は typical に入れず high に入れています。人時の大きい順に確認します。">
        <Table head={["未確認の項目", "状態", "high だけに入る人時"]}>
          {checks.checklist.map((row: Obj) => (
            <tr key={row.item}>
              <th scope="row">{row.item}</th>
              <td>{row.state}</td>
              <td className="num">{row.high_only_hours}</td>
            </tr>
          ))}
        </Table>
        <ul className="mh-list">
          <li>
            確認強度: {checks.check_intensity.level}
            {checks.check_intensity.extra_items.length ? `（追加: ${checks.check_intensity.extra_items.join("、")}）` : ""}
          </li>
          <li>
            確認優先度: {checks.priority.score} 点（{checks.priority.band}・{checks.priority.when}）
          </li>
          <li>気象による前処理の確認: {checks.weather_prompt.prompt ? "促す" : "不要"}</li>
          <li>
            撮影: {checks.photos.taken}/{checks.photos.required} 枚
            {checks.photos.coverage_percent === null ? "" : `（${checks.photos.coverage_percent}%）`}
            {Object.keys(checks.photos.missing).length ? `　未撮影: ${Object.keys(checks.photos.missing).join("、")}` : ""}
          </li>
          <li>
            AI の一次分類: 比較 {checks.ai_classification.compared} 件、一致 {checks.ai_classification.agree} 件
            {checks.ai_classification.disagree.length ? `（不一致: ${checks.ai_classification.disagree.join("、")}）` : ""}
          </li>
          {checks.same_vehicle ? (
            <li>
              同一車両の前回: {checks.same_vehicle.previous_record}（{checks.same_vehicle.previous_date}）から{" "}
              {checks.same_vehicle.km_since_previous}km。{checks.same_vehicle.note}
            </li>
          ) : null}
        </ul>
        <h3>未確認・範囲外</h3>
        <ul className="mh-list">
          {result.unknowns.length ? result.unknowns.map((u: string) => <li key={u}>{u}</li>) : <li>なし</li>}
        </ul>
        {result.excluded_from_this_job.length ? (
          <>
            <h3>今回の作業に含まれないため除外</h3>
            <ul className="mh-list">
              {result.excluded_from_this_job.map((u: string) => (
                <li key={u}>{u}</li>
              ))}
            </ul>
          </>
        ) : null}
      </Section>

      <Section title="発生した場合だけの追加と作業前連絡" note={result.conditional_quote.note}>
        <Table head={["条件", "追加人時", "追加金額（円）", "作業前連絡"]}>
          {result.conditional_quote.conditions.map((q: Obj) => (
            <tr key={q.condition}>
              <th scope="row">{q.condition}</th>
              <td className="num">{q.extra_hours}</td>
              <td className="num">{q.extra_yen}</td>
              <td>{q.contact_before_work ? "要" : "不要"}</td>
            </tr>
          ))}
        </Table>
        <p className="mh-note">すべて発生した場合の追加人時の合計: {result.conditional_quote.all_conditions_extra_hours}</p>
      </Section>

      <Section title="工賃と材料費" note={result.money.note}>
        <Table head={["時間単価", "円/人時"]}>
          <tr>
            <th scope="row">適用（{result.money.labor_rate.mode}）</th>
            <td className="num">{result.money.labor_rate.applied_yen_per_hour}</td>
          </tr>
          <tr>
            <th scope="row">年間で配賦</th>
            <td className="num">{result.money.labor_rate.annual_yen_per_hour}</td>
          </tr>
          <tr>
            <th scope="row">冬季で配賦</th>
            <td className="num">{result.money.labor_rate.seasonal_winter_yen_per_hour}</td>
          </tr>
          <tr>
            <th scope="row">冬季以外で配賦</th>
            <td className="num">{result.money.labor_rate.seasonal_non_winter_yen_per_hour}</td>
          </tr>
        </Table>
        <p className="mh-note">
          工賃 = {result.money.labor_yen_basis}。{result.money.labor_rate.note}
        </p>
      </Section>

      <Section title="顧客向けの内訳">
        <Table head={["項目", "typical", "high", "根拠"]}>
          {result.customer_sheet.map((line: Obj) => (
            <tr key={line.line}>
              <th scope="row">{line.line}</th>
              <td className="num">{line.typical}</td>
              <td className="num">{line.high}</td>
              <td>{line.basis}</td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section title="補正表の候補（v2）" note={result.rates.note}>
        <p>
          採用中: <strong>{adopted}</strong>。候補の版: {result.rates.candidate}。候補で計算した人時:
        </p>
        <Table head={["", "low", "typical", "high"]}>
          <tr>
            <th scope="row">候補（{result.rates.candidate}）の人時</th>
            <Bands values={result.rates.candidate_labor_hours} />
          </tr>
        </Table>
        <Table head={["実績タグ", "工程", "件数", "最小", "中央値", "最大", "v2 に使う"]}>
          {result.rates.evidence.map((row: Obj) => (
            <tr key={row.tag}>
              <th scope="row">{row.tag}</th>
              <td>{row.op}</td>
              <td className="num">{row.n}</td>
              <td className="num">{show(row.min)}</td>
              <td className="num">{show(row.median)}</td>
              <td className="num">{show(row.max)}</td>
              <td>{row.used_for_v2 ? "使う" : "件数不足"}</td>
            </tr>
          ))}
        </Table>
        {result.rates.other_shops.length ? (
          <Table head={["他工場の参照幅（工程）", "最小", "最大", "自工場の typical", "幅の中"]}>
            {result.rates.other_shops.map((row: Obj) => (
              <tr key={row.op}>
                <th scope="row">{row.op}</th>
                <td className="num">{row.other_shops_min}</td>
                <td className="num">{row.other_shops_max}</td>
                <td className="num">{row.own_typical}</td>
                <td>{row.inside ? "はい" : "いいえ"}</td>
              </tr>
            ))}
          </Table>
        ) : null}
        <label className="mh-field">
          承認者（担当者コード）
          <input value={approver} onChange={(event) => setApprover(event.target.value)} />
        </label>
        <div className="mh-actions">
          <button type="button" disabled={busy || !databaseReady || adopted === "v2"} onClick={() => approve("v2")}>
            v2 を承認して採用する
          </button>
          <button type="button" className="secondary" disabled={busy || !databaseReady || adopted === "v1"} onClick={() => approve("v1")}>
            v1（暫定値）に戻す
          </button>
        </div>
        {databaseReady ? null : <p className="mh-note">承認と保存には DB が必要です（現在は同梱の JSON で計算しています）。</p>}
      </Section>
    </>
  );
}
