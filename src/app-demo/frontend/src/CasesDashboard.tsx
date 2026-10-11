import React, { useEffect, useState } from "react";
import "./cases.css";

export type CaseStatus = "unestimated" | "estimating" | "completed";
export type EstimateCase = {
  id: string;
  title: string;
  vehicle_label: string;
  status: CaseStatus;
  amount: number | null;
  due_date: string | null;
  notes: string;
  latest_estimate_id: string | null;
  created_at: string;
  updated_at: string;
};
export const caseStatuses: Record<CaseStatus, string> = {
  unestimated: "未見積もり",
  estimating: "見積もり中",
  completed: "完了",
};
export async function caseRequest<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api/cases" + path, {
    method,
    ...(body === undefined
      ? {}
      : {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "案件を保存できませんでした。入力内容・通信状態を確認してください。",
    );
  }
  return response.json();
}
export function caseFields(c: EstimateCase) {
  return {
    title: c.title,
    vehicle_label: c.vehicle_label,
    status: c.status,
    amount: c.amount,
    due_date: c.due_date,
    notes: c.notes,
  };
}
const yen = (value: number) =>
  new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY" }).format(
    value,
  );
const blank = {
  title: "",
  vehicle_label: "",
  status: "unestimated" as CaseStatus,
  amount: "",
  due_date: "",
  notes: "",
};

export default function CasesDashboard({
  revision,
  onOpen,
}: {
  revision: number;
  onOpen: (c: EstimateCase) => Promise<void>;
}) {
  const [cases, setCases] = useState<EstimateCase[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<CaseStatus | "all">("all");
  const [sort, setSort] = useState("created");
  const [layout, setLayout] = useState<"standard" | "details">(() => {
    try {
      return localStorage.getItem("repair-case-layout") === "details"
        ? "details"
        : "standard";
    } catch {
      return "standard";
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("repair-case-layout", layout);
    } catch {
      /* Storage may be unavailable. */
    }
  }, [layout]);
  const [form, setForm] = useState<typeof blank | null>(null);
  const [editing, setEditing] = useState<EstimateCase | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    setLoading(true);
    caseRequest<EstimateCase[]>("")
      .then((result) => {
        if (active) {
          setCases(result);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [revision, reload]);
  const today = new Date().toLocaleDateString("sv-SE");
  const overdue = (c: EstimateCase) =>
    !!c.due_date && c.due_date < today && c.status !== "completed";
  const visible = cases
    .filter(
      (c) =>
        (filter === "all" || c.status === filter) &&
        [c.id, c.title, c.vehicle_label, c.notes]
          .join(" ")
          .toLocaleLowerCase()
          .includes(query.trim().toLocaleLowerCase()),
    )
    .sort((a, b) =>
      sort === "due"
        ? (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999") ||
          b.created_at.localeCompare(a.created_at)
        : b.created_at.localeCompare(a.created_at),
    );
  function edit(c: EstimateCase | null) {
    setEditing(c);
    setForm(
      c
        ? {
            title: c.title,
            vehicle_label: c.vehicle_label,
            status: c.status,
            amount: c.amount === null ? "" : String(c.amount),
            due_date: c.due_date ?? "",
            notes: c.notes,
          }
        : { ...blank },
    );
    setError("");
    setNotice("");
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!form) return;
    setBusy(true);
    setError("");
    try {
      const c = await caseRequest<EstimateCase>(
        editing ? "/" + editing.id : "",
        editing ? "PUT" : "POST",
        {
          ...form,
          amount: form.amount === "" ? null : Number(form.amount),
          due_date: form.due_date || null,
        },
      );
      setForm(null);
      setNotice(`${c.title}を${editing ? "更新" : "登録"}しました。`);
      setReload((n) => n + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function open(c: EstimateCase) {
    setBusy(true);
    setError("");
    try {
      await onOpen(c);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="cases-page">
      <div className="cases-heading">
        <div>
          <h1>見積もり案件</h1>
          <p>受付から見積もり完了まで、案件ごとに確認。</p>
        </div>
        <button
          className="primary-button"
          disabled={busy}
          onClick={() => edit(null)}
        >
          ＋ 新規案件
        </button>
      </div>
      <p className="cases-explanation">
        金額は税込の予定額です。見積もりを保存すると、確定した見積金額に更新し「完了」になります。売上・利益は別画面のサンプルです。
      </p>
      <div
        className="case-status-tabs"
        role="group"
        aria-label="案件ステータスで絞り込み"
      >
        {(["all", "unestimated", "estimating", "completed"] as const).map(
          (status) => (
            <button
              key={status}
              aria-pressed={filter === status}
              onClick={() => setFilter(status)}
            >
              {status === "all" ? "すべて" : caseStatuses[status]}
              <span>
                {status === "all"
                  ? cases.length
                  : cases.filter((c) => c.status === status).length}
              </span>
            </button>
          ),
        )}
      </div>
      {error && (
        <div className="error-message" role="alert">
          {error}
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() => setReload((n) => n + 1)}
          >
            再読み込み
          </button>
        </div>
      )}
      {notice && (
        <p className="case-notice" role="status">
          {notice}
        </p>
      )}
      {form && (
        <section
          className="case-form-panel"
          aria-label={editing ? "案件を編集" : "案件を登録"}
        >
          <div className="case-form-title">
            <h2>{editing ? "案件を編集" : "案件を登録"}</h2>
            {editing && <span className="case-id">{editing.id}</span>}
          </div>
          <form onSubmit={save} className="case-form">
            <label>
              案件名
              <input
                autoFocus
                required
                maxLength={120}
                value={form.title}
                placeholder="例：シビック オイル・バッテリー交換"
                onChange={(e) => setForm({ ...form, title: e.target.value })}
              />
            </label>
            <label>
              車両メモ
              <input
                maxLength={160}
                value={form.vehicle_label}
                placeholder="例：ホンダ シビック / FL4"
                onChange={(e) =>
                  setForm({ ...form, vehicle_label: e.target.value })
                }
              />
            </label>
            <label>
              ステータス
              <select
                aria-label="ステータス"
                value={form.status}
                onChange={(e) =>
                  setForm({ ...form, status: e.target.value as CaseStatus })
                }
              >
                {Object.entries(caseStatuses).map(([id, label]) => (
                  <option value={id} key={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              予定金額（税込・円）
              <input
                type="number"
                min={0}
                max={110000000}
                step={1}
                value={form.amount}
                placeholder="未設定"
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
              />
            </label>
            <label>
              納期
              <input
                type="date"
                value={form.due_date}
                onChange={(e) => setForm({ ...form, due_date: e.target.value })}
              />
            </label>
            <label className="case-form-notes">
              案件メモ
              <textarea
                maxLength={2000}
                rows={2}
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
              />
            </label>
            <div className="case-form-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() => setForm(null)}
              >
                キャンセル
              </button>
              <button
                type="submit"
                className="primary-button"
                disabled={busy || !form.title.trim()}
              >
                {busy ? "保存中…" : editing ? "変更を保存" : "案件を登録"}
              </button>
            </div>
          </form>
        </section>
      )}
      <section className="case-register" aria-label="案件一覧">
        <div className="case-tools">
          <label>
            案件を検索
            <input
              type="search"
              value={query}
              placeholder="案件ID・案件名・型式・メモ"
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <label>
            並び順
            <select
              aria-label="並び順"
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              <option value="created">登録が新しい順</option>
              <option value="due">納期が近い順</option>
            </select>
          </label>
          <div
            className="case-layout-toggle"
            role="group"
            aria-label="案件一覧の表示方法"
          >
            <button
              aria-pressed={layout === "standard"}
              onClick={() => setLayout("standard")}
            >
              通常表示
            </button>
            <button
              aria-pressed={layout === "details"}
              onClick={() => setLayout("details")}
            >
              詳細表示
            </button>
          </div>
          <span>{visible.length} 件</span>
        </div>
        <div className="case-table-scroll">
          <table
            className={`case-table ${layout === "details" ? "case-table--details" : ""}`}
          >
            <caption className="sr-only">
              案件ID・ステータス・金額・納期の一覧
            </caption>
            <thead>
              <tr>
                <th>{layout === "details" ? "案件名" : "案件 / ID"}</th>
                {layout === "details" && (
                  <>
                    <th>案件ID</th>
                    <th>車両</th>
                  </>
                )}
                <th>ステータス</th>
                <th>金額（税込）</th>
                <th>納期</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((c) => (
                <tr key={c.id}>
                  <td>
                    <strong title={c.title}>{c.title}</strong>
                    {layout === "standard" && (
                      <>
                        <span className="case-vehicle">
                          {c.vehicle_label || "車両未設定"}
                        </span>
                        <span className="case-id" title={c.id}>
                          {c.id}
                        </span>
                        {c.notes && (
                          <span className="case-memo">{c.notes}</span>
                        )}
                      </>
                    )}
                  </td>
                  {layout === "details" && (
                    <>
                      <td className="case-detail-id" title={c.id}>
                        {c.id}
                      </td>
                      <td
                        className="case-detail-vehicle"
                        title={c.vehicle_label || "車両未設定"}
                      >
                        {c.vehicle_label || "車両未設定"}
                      </td>
                    </>
                  )}
                  <td>
                    <span className={`case-status ${c.status}`}>
                      {caseStatuses[c.status]}
                    </span>
                  </td>
                  <td className="case-money">
                    {c.amount === null ? (
                      <span className="muted">未設定</span>
                    ) : (
                      yen(c.amount)
                    )}
                    {c.latest_estimate_id && <small>見積もり保存済み</small>}
                  </td>
                  <td
                    className={overdue(c) ? "case-late" : undefined}
                    title={overdue(c) ? "納期を過ぎています" : undefined}
                  >
                    <time dateTime={c.due_date ?? undefined}>
                      {c.due_date?.replaceAll("-", "/") ?? "未設定"}
                    </time>
                    {overdue(c) && (
                      <small className="case-overdue">納期を過ぎています</small>
                    )}
                  </td>
                  <td>
                    <div className="case-row-actions">
                      <button
                        className="case-open"
                        disabled={busy || !!form}
                        onClick={() => open(c)}
                      >
                        {c.latest_estimate_id
                          ? "見積もりを開く"
                          : "見積もりを作成"}
                      </button>
                      <button
                        className="case-edit"
                        disabled={busy}
                        onClick={() => edit(c)}
                        aria-label={`${c.title}を編集`}
                      >
                        編集
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {layout === "details" && (
          <p className="case-detail-hint">
            長い案件名・IDはカーソルを合わせると確認できます。狭い画面では表を横にスクロールできます。
          </p>
        )}
        {loading ? (
          <p className="case-empty" role="status">
            案件を読み込んでいます…
          </p>
        ) : (
          !visible.length && (
            <p className="case-empty">
              {cases.length
                ? "該当する案件はありません。検索条件を変更してください。"
                : "最初の案件を「新規案件」から登録してください。IDは自動で発行します。"}
            </p>
          )
        )}
      </section>
      <p className="cases-storage">
        案件・金額・納期は、このデモのローカルデータベースに保存されます。
      </p>
    </main>
  );
}
