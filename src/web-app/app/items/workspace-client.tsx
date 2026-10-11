"use client";

// workspace.html（材料・見積ワークスペース）の React 版。操作と文言は元と同じ。
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

type View = "dashboard" | "register" | "import" | "quote" | "usage";
type Row = Record<string, unknown>;
type Dashboard = {
  summary: { item_count: number; price_count: number; issue_count: number };
  inventory: (Row & { issues: string[] })[];
  quotes: Row[];
};
type StagedRow = { record_id: string; item: Row | null; errors?: string[] };
type QuoteLine = { key: number; item_id: string; quantity: string; unit: string; supplier_id: string };

async function api(payload: Row): Promise<Row> {
  const response = await fetch("/api/items/workspace", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = (await response.json()) as Row;
  if (!response.ok) throw Error(data.error as string);
  return data.result as Row;
}

function today(): string {
  return new Date().toLocaleDateString("sv-SE");
}

function fields(form: HTMLFormElement): Record<string, string> {
  return Object.fromEntries(new FormData(form)) as Record<string, string>;
}

function DataTable({ rows, keys }: { rows: Row[]; keys: [string, string][] }) {
  return (
    <div className="scroll">
      <table>
        <tbody>
          <tr>
            {keys.map(([key, label]) => (
              <th key={key}>{label}</th>
            ))}
          </tr>
          {rows.map((row, index) => (
            <tr key={index}>
              {keys.map(([key]) => (
                <td key={key}>{row[key] === null || row[key] === undefined ? "未確認" : String(row[key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Pre({ value }: { value: unknown }) {
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

let lineKey = 0;
const newLine = (): QuoteLine => ({ key: ++lineKey, item_id: "", quantity: "1", unit: "ml", supplier_id: "" });

export default function WorkspaceClient() {
  const [view, setView] = useState<View>("dashboard");
  const [status, setStatus] = useState("読み込み中");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [batch, setBatch] = useState<Row | null>(null);
  const [candidates, setCandidates] = useState<StagedRow[] | null>(null);
  const [approvalResult, setApprovalResult] = useState<Row | null>(null);
  const [checked, setChecked] = useState<string[]>([]);
  const [lines, setLines] = useState<QuoteLine[]>(() => [newLine()]);
  const [savedQuote, setSavedQuote] = useState<Row | null>(null);
  const [usageResult, setUsageResult] = useState<Row | null>(null);
  const [usageQuote, setUsageQuote] = useState({ quote_id: "", quote_line_id: "" });
  const [date, setDate] = useState("");
  const csvRef = useRef<HTMLTextAreaElement>(null);

  const task = useCallback(async (fn: () => Promise<void>) => {
    try {
      setStatus("処理中…");
      await fn();
      setStatus("完了しました");
    } catch (error) {
      setStatus("要確認：" + (error as Error).message);
    }
  }, []);

  const refresh = useCallback(async () => {
    setDashboard((await api({ action: "dashboard", as_of: today() })) as unknown as Dashboard);
  }, []);

  useEffect(() => {
    // 日付の初期値（今日）と確認状況の読み込みは、画面を開いたときに1回だけ行う。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDate(today());
    void task(refresh);
  }, [task, refresh]);

  const renderQuote = (result: Row) => {
    const quote = result.quote as Row & { lines: Row[] };
    setSavedQuote(quote);
    setUsageQuote({ quote_id: String(quote.quote_id), quote_line_id: quote.lines[0] ? String(quote.lines[0].quote_line_id) : "" });
  };

  const onRegister = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    void task(async () => {
      const data: Row = fields(form);
      const item: Row = {};
      for (const key of ["item_id", "name", "category", "unit", "unit_price", "price_type", "source", "updated_at"]) {
        item[key] = data[key];
        delete data[key];
      }
      if ((data.conditions as string).trim()) data.conditions = JSON.parse(data.conditions as string);
      else delete data.conditions;
      if (!data.valid_until) delete data.valid_until;
      if (!(data.supplier_id as string).trim()) delete data.supplier_id;
      await api({ action: "register", item, ...data });
      await refresh();
    });
  };

  const onStage = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    void task(async () => {
      const result = await api({ action: "stage_csv", ...fields(form) });
      setBatch(result);
      setApprovalResult(null);
      setChecked([]);
      setCandidates((result.staged_rows as StagedRow[]) || []);
    });
  };

  const onApprove = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    void task(async () => {
      const result = await api({ action: "approve_import", import_batch_id: batch?.import_batch_id, candidate_ids: checked, ...fields(form) });
      setCandidates(null);
      setApprovalResult(result);
      setBatch(null);
      await refresh();
    });
  };

  const onSaveQuote = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement).value;
    void task(async () => {
      renderQuote(
        await api({
          action: "save_quote",
          quote_id: value("quote_id"),
          as_of: value("as_of"),
          confirmed_by: value("confirmed_by"),
          lines: lines.map((line) => ({
            item_id: line.item_id,
            quantity: line.quantity,
            unit: line.unit,
            supplier_id: line.supplier_id,
            price_type: "販売",
          })),
        }),
      );
    });
  };

  const onGetQuote = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    void task(async () => renderQuote(await api({ action: "get_quote", ...fields(form) })));
  };

  const onUsage = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    void task(async () => setUsageResult(await api({ action: "record_usage", ...fields(form) })));
  };

  const updateLine = (key: number, name: keyof Omit<QuoteLine, "key">, value: string) =>
    setLines((current) => current.map((line) => (line.key === key ? { ...line, [name]: value } : line)));

  return (
    <div className="sys-items items-ws">
      <header>
        <Link href="/" className="items-home-link">
          ← トップへ戻る
        </Link>
        <div>
          <small>材料マスタ / 統合版</small>
        </div>
        <h1>材料から見積、実績まで</h1>
        <p className="note">検証用。初期データは架空値です。PDF・OCR・卸APIの実接続はありません。</p>
        <nav>
          <button type="button" onClick={() => setView("dashboard")}>確認状況</button>
          <button type="button" onClick={() => setView("register")}>材料・価格登録</button>
          <button type="button" onClick={() => setView("import")}>CSV取込</button>
          <button type="button" onClick={() => setView("quote")}>見積作成・再表示</button>
          <button type="button" onClick={() => setView("usage")}>実使用量</button>
          <Link href="/items/ideas">30案の個別機能</Link>
        </nav>
      </header>
      <main>
        <p className="status" role="status">
          {status}
        </p>

        <section id="dashboard" hidden={view !== "dashboard"}>
          <h2>価格と確認状況</h2>
          <button type="button" onClick={() => void task(refresh)}>
            再読込
          </button>
          {dashboard && (
            <div>
              <p>
                材料 {dashboard.summary.item_count} 件 / 価格 {dashboard.summary.price_count} 件 / 要確認 {dashboard.summary.issue_count} 件
              </p>
              <DataTable
                rows={dashboard.inventory.map((row) => ({
                  ...row,
                  check: row.issues.length ? row.issues.join("・") : "確認済み",
                  valid_until: row.valid_until || "期限なし",
                }))}
                keys={[
                  ["name", "材料"],
                  ["price_type", "区分"],
                  ["unit_price", "単価"],
                  ["unit", "単位"],
                  ["supplier_id", "仕入先"],
                  ["valid_until", "有効期限"],
                  ["check", "確認状況"],
                ]}
              />
              <h3>保存済み見積</h3>
              <div className="quote-buttons">
                {dashboard.quotes.map((quote, index) => (
                  <button
                    type="button"
                    key={index}
                    onClick={() =>
                      void task(async () => {
                        setView("quote");
                        renderQuote(await api({ action: "get_quote", quote_id: quote.quote_id }));
                      })
                    }
                  >
                    {String(quote.quote_id)} を再表示
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>

        <section id="register" hidden={view !== "register"}>
          <h2>材料・価格の登録</h2>
          <form onSubmit={onRegister}>
            <div className="grid">
              <label>材料ID<input name="item_id" required /></label>
              <label>材料名<input name="name" required /></label>
              <label>
                分類
                <select name="category">
                  <option>塗料</option>
                  <option>部品</option>
                  <option>溶剤</option>
                  <option>消耗品</option>
                </select>
              </label>
              <label>単位<input name="unit" defaultValue="ml" required /></label>
              <label>単価<input name="unit_price" inputMode="decimal" required /></label>
              <label>
                価格区分
                <select name="price_type">
                  <option>販売</option>
                  <option>仕入</option>
                </select>
              </label>
              <label>出所<input name="source" required /></label>
              <label>価格更新日<input name="updated_at" type="date" defaultValue={date} key={`u${date}`} required /></label>
              <label>人が確認した日<input name="checked_at" type="date" defaultValue={date} key={`c${date}`} required /></label>
              <label>仕入先ID（任意）<input name="supplier_id" /></label>
              <label>有効開始日<input name="valid_from" type="date" defaultValue={date} key={`f${date}`} required /></label>
              <label>有効終了日（新規は期限なし、更新は既存期限を引継ぎ）<input name="valid_until" type="date" /></label>
              <label>確認者<input name="confirmed_by" required /></label>
            </div>
            <label>
              取引条件（変更時だけ入力。空欄なら既存条件を引継ぎ）
              <textarea name="conditions" rows={2} placeholder='{"currency":"JPY","freight_basis":"included"}' />
            </label>
            <label>登録・変更理由<input name="reason" required /></label>
            <button>確認して価格版を保存</button>
          </form>
        </section>

        <section id="import" hidden={view !== "import"}>
          <h2>CSV取込と行の承認</h2>
          <p>列名：item_id,name,category,unit,unit_price,price_type,source,updated_at</p>
          <form onSubmit={onStage}>
            <label>
              CSVファイル
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={async (event) => {
                  const file = event.target.files?.[0];
                  if (file && csvRef.current) csvRef.current.value = await file.text();
                }}
              />
            </label>
            <label>CSV本文<textarea ref={csvRef} name="csv_text" rows={6} required /></label>
            <label>出所<input name="source" required /></label>
            <button>候補を読み込む</button>
          </form>
          <div>
            {candidates?.map((row) => (
              <label key={row.record_id} className="candidate-label">
                <input
                  type="checkbox"
                  value={row.record_id}
                  disabled={!!row.errors?.length}
                  checked={checked.includes(row.record_id)}
                  onChange={(event) =>
                    setChecked((current) =>
                      event.target.checked ? [...current, row.record_id] : current.filter((id) => id !== row.record_id),
                    )
                  }
                />
                {JSON.stringify(row.item || row.errors)}
              </label>
            ))}
            {approvalResult && <Pre value={approvalResult} />}
          </div>
          <form onSubmit={onApprove} hidden={candidates === null}>
            <label>確認者<input name="confirmed_by" required /></label>
            <button>選択した候補を承認して登録</button>
          </form>
        </section>

        <section id="quote" hidden={view !== "quote"}>
          <h2>見積の作成・保存</h2>
          <form onSubmit={onSaveQuote}>
            <div className="grid">
              <label>見積ID<input name="quote_id" required /></label>
              <label>価格適用日<input name="as_of" type="date" defaultValue={date} key={`a${date}`} required /></label>
              <label>確認者<input name="confirmed_by" required /></label>
            </div>
            <div>
              {lines.map((line) => (
                <fieldset className="grid" key={line.key}>
                  {(
                    [
                      ["item_id", "材料ID"],
                      ["quantity", "数量"],
                      ["unit", "単位"],
                      ["supplier_id", "仕入先ID（任意）"],
                    ] as const
                  ).map(([name, label]) => (
                    <label key={name}>
                      {label}
                      <input
                        name={name}
                        value={line[name]}
                        required={name !== "supplier_id"}
                        onChange={(event) => updateLine(line.key, name, event.target.value)}
                      />
                    </label>
                  ))}
                  <button type="button" onClick={() => setLines((current) => current.filter((entry) => entry.key !== line.key))}>
                    この行を削除
                  </button>
                </fieldset>
              ))}
            </div>
            <button type="button" onClick={() => setLines((current) => [...current, newLine()])}>
              材料を追加
            </button>{" "}
            <button>単価を固定して保存</button>
          </form>
          <hr />
          <form onSubmit={onGetQuote}>
            <label>保存済み見積ID<input name="quote_id" required /></label>
            <button>保存時点の見積を表示</button>
          </form>
          <div>
            {savedQuote && (
              <>
                <p>
                  保存時点の見積 {String(savedQuote.quote_id)} / 小計 {String(savedQuote.subtotal)} 円（税・端数処理前）
                </p>
                <DataTable
                  rows={savedQuote.lines as Row[]}
                  keys={[
                    ["quote_line_id", "見積行ID"],
                    ["name", "材料名"],
                    ["quantity", "数量"],
                    ["unit", "単位"],
                    ["unit_price_snapshot", "保存単価"],
                    ["line_total", "金額"],
                  ]}
                />
              </>
            )}
          </div>
        </section>

        <section id="usage" hidden={view !== "usage"}>
          <h2>実使用量と見積量の比較</h2>
          <form onSubmit={onUsage}>
            <div className="grid">
              <label>
                見積ID
                <input
                  name="quote_id"
                  value={usageQuote.quote_id}
                  onChange={(event) => setUsageQuote((current) => ({ ...current, quote_id: event.target.value }))}
                  required
                />
              </label>
              <label>
                見積行ID
                <input
                  name="quote_line_id"
                  value={usageQuote.quote_line_id}
                  onChange={(event) => setUsageQuote((current) => ({ ...current, quote_line_id: event.target.value }))}
                  required
                />
              </label>
              <label>実使用量<input name="actual_qty" inputMode="decimal" required /></label>
              <label>確認者<input name="confirmed_by" required /></label>
            </div>
            <label>差分の理由<input name="reason" required /></label>
            <button>実績を記録</button>
          </form>
          <div>{usageResult && <Pre value={usageResult} />}</div>
        </section>
      </main>
    </div>
  );
}
