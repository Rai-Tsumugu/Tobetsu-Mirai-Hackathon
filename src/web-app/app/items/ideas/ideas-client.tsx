"use client";

// index.html（材料台帳 · 30の道具）の React 版。各案の既定入力からフォームを作り、結果を表で表示する。
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";

type Spec = { idea_id: string; title: string; description: string; defaults: Record<string, unknown> };
type Field = {
  path: string[];
  key: string;
  kind: "array" | "boolean" | "file" | "select" | "textarea" | "number" | "nullable" | "string";
  options?: string[];
  initial: string;
  wide: boolean;
};
type Group = { key: string; children: Node[] };
type Node = Field | Group;

const labels: Record<string, string> = {
  item_id: "品目ID",
  name: "品名",
  category: "分類",
  unit: "基準単位",
  unit_price: "単価（架空・円）",
  price_type: "価格区分",
  source: "出所",
  updated_at: "確認日",
  confirmed_by: "確認・承認した人",
  reason: "理由",
  action: "操作",
  maker: "メーカー",
  raw_code: "色コードの原表記",
  finish: "仕上げ",
  supplier_id: "仕入先ID",
  source_unit: "元の単位",
  base_unit: "換算後の単位",
  factor: "入数・換算係数",
  quantity: "数量",
  package_price: "包装価格",
  evidence: "換算・使用量の根拠",
  item: "品目",
  as_of: "確認する日",
  valid_from: "有効開始日",
  valid_until: "有効期限",
  price_version_id: "価格版ID",
  formula_id: "配合ID",
  formula_version: "配合版",
  formula_lines: "構成材料",
  lines: "明細",
  ratio: "配合比",
  total_quantity: "必要総量",
  operation_id: "工程ID",
  panel_id: "部位ID",
  finish_type: "仕上げ",
  area_band: "面積帯",
  low_qty: "数量下限",
  typical_qty: "標準数量",
  high_qty: "数量上限",
  csv_text: "CSVの表（品目情報のみ）",
  field_map: "列の対応",
  rows: "読取候補の明細（架空値）",
  sheet_name: "シート名",
  document_id: "伝票参照ID",
  page: "ページ",
  region: "選択した明細範囲",
  candidates: "確認待ちの候補",
  terms_status: "利用条件の確認状態",
  confirmed_fields: "確認した項目",
  corrections: "訂正する項目",
  quote_id: "見積ID",
  quote_line_id: "見積行ID",
  estimated_qty: "見積数量",
  actual_qty: "実使用量",
  multiplier: "掛率（人が決めた値）",
  stage: "丸め対象",
  rounding_mode: "丸め方式",
  decimal_places: "小数桁数",
  min_qty: "適用最小数量",
  checked_at: "人が確認した日",
  source_updated_at: "出所の更新日",
  status: "確認状態",
  decision: "採用判断",
  amount: "金額",
  old_price: "変更前の価格",
  new_price: "変更後の価格",
  index_observation: "原料指数（参考値）",
  series: "指数系列",
  value: "値",
  published_at: "公表日",
  fetched_at: "取得日",
  version: "版",
  approved_by: "承認者",
  method: "方法",
  mode: "方式",
  tax_rate: "税率（架空の設定値）",
  tax: "税額",
  total: "合計",
  subtotal: "小計",
  items: "品目",
  conditions: "適用条件",
  price_versions: "価格履歴",
  basis: "計算根拠",
  warnings: "確認事項",
  simulation_only: "試算のみ",
  record_id: "記録ID",
};

const label = (key: string) => labels[key] || key.replaceAll("_", " ");

function display(value: unknown): string {
  if (value === null) return "未確認";
  if (typeof value === "boolean") return value ? "はい" : "いいえ";
  return String(value);
}

function ValueTable({ value }: { value: unknown }): ReactNode {
  if (Array.isArray(value)) {
    if (!value.length) return <div>該当なし</div>;
    return (
      <div>
        {value.map((entry, index) =>
          typeof entry === "object" && entry !== null ? (
            <div className="nested" key={index}>
              <p>{`${index + 1}件目`}</p>
              <ValueTable value={entry} />
            </div>
          ) : (
            <div className="nested" key={index}>
              {display(entry)}
            </div>
          ),
        )}
      </div>
    );
  }
  if (value && typeof value === "object") {
    return (
      <div>
        <table>
          <tbody>
            {Object.entries(value).map(([key, entry]) => (
              <tr key={key}>
                <th>{label(key)}</th>
                <td>{entry && typeof entry === "object" ? <ValueTable value={entry} /> : display(entry)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return <div>{display(value)}</div>;
}

function buildFields(defaults: Record<string, unknown>, path: string[] = []): Node[] {
  return Object.entries(defaults).map(([key, value]): Node => {
    const fieldPath = [...path, key];
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return { key, children: buildFields(value as Record<string, unknown>, fieldPath) };
    }
    if (Array.isArray(value)) return { path: fieldPath, key, kind: "array", initial: JSON.stringify(value, null, 2), wide: true };
    if (typeof value === "boolean") return { path: fieldPath, key, kind: "boolean", initial: String(value), wide: false };
    if (key === "xlsx_base64") return { path: fieldPath, key, kind: "file", initial: "", wide: false };
    if (key === "category" || key === "price_type") {
      return {
        path: fieldPath,
        key,
        kind: "select",
        options: key === "category" ? ["部品", "塗料", "溶剤", "消耗品"] : ["仕入", "販売"],
        initial: String(value),
        wide: false,
      };
    }
    if (typeof value === "string" && value.includes("\n")) return { path: fieldPath, key, kind: "textarea", initial: value, wide: true };
    return {
      path: fieldPath,
      key,
      kind: typeof value === "number" ? "number" : value === null ? "nullable" : "string",
      initial: value === null ? "" : String(value),
      wide: false,
    };
  });
}

function collectFields(nodes: Node[], out: Field[] = []): Field[] {
  for (const node of nodes) {
    if ("children" in node) collectFields(node.children, out);
    else out.push(node);
  }
  return out;
}

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.length > 2500000) throw Error("Excelファイルは2.5MB以下にしてください");
  let binary = "";
  bytes.forEach((byte) => (binary += String.fromCharCode(byte)));
  return btoa(binary);
}

export default function IdeasClient() {
  const [specs, setSpecs] = useState<Spec[]>([]);
  const [count, setCount] = useState("読み込み中…");
  const [active, setActive] = useState<Spec | null>(null);
  const [formKey, setFormKey] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<Record<string, File | undefined>>({});
  const [status, setStatus] = useState<{ text: string; error: boolean }>({ text: "", error: false });
  const [result, setResult] = useState<{ value: unknown } | null>(null);
  const [history, setHistory] = useState<{ value: unknown } | null>(null);
  const [busy, setBusy] = useState(false);

  const select = useCallback((spec: Spec) => {
    setActive(spec);
    setValues(Object.fromEntries(collectFields(buildFields(spec.defaults)).map((field) => [JSON.stringify(field.path), field.initial])));
    setFiles({});
    setStatus({ text: "", error: false });
    setFormKey((key) => key + 1);
  }, []);

  const loadHistory = useCallback(async () => {
    const response = await fetch("/api/items/prices");
    if (!response.ok) throw Error("台帳の読込に失敗しました");
    const data = (await response.json()) as { price_versions: unknown };
    setHistory({ value: data.price_versions });
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const response = await fetch("/api/items/ideas");
        const data = (await response.json()) as { ideas: Spec[] };
        setSpecs(data.ideas);
        setCount(`30案の道具 · ${data.ideas.length}案を利用可能`);
        if (data.ideas.length) select(data.ideas.find((spec) => spec.idea_id === "M07") || data.ideas[0]);
        await loadHistory();
      } catch (error) {
        setCount("読込に失敗しました");
        setStatus({ text: (error as Error).message, error: false });
      }
    })();
  }, [select, loadHistory]);

  const collect = async (): Promise<Record<string, unknown>> => {
    const payload = JSON.parse(JSON.stringify(active!.defaults)) as Record<string, unknown>;
    for (const field of collectFields(buildFields(active!.defaults))) {
      let target = payload;
      field.path.slice(0, -1).forEach((key) => (target = target[key] as Record<string, unknown>));
      const raw = values[JSON.stringify(field.path)] ?? "";
      let value: unknown = raw;
      switch (field.kind) {
        case "array":
          value = JSON.parse(raw);
          break;
        case "boolean":
          value = raw === "true";
          break;
        case "number":
          value = raw === "" ? null : Number(raw);
          break;
        case "nullable":
          value = raw || null;
          break;
        case "file": {
          const file = files[JSON.stringify(field.path)];
          value = file ? await fileToBase64(file) : target[field.path.at(-1)!];
          break;
        }
      }
      target[field.path.at(-1)!] = value;
    }
    return payload;
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!active) return;
    setBusy(true);
    setStatus({ text: "確認中…", error: false });
    try {
      const response = await fetch(`/api/items/ideas/${active.idea_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(await collect()),
      });
      const data = (await response.json()) as { result?: unknown; error?: string };
      if (!response.ok) throw Error(data.error);
      setResult({ value: data.result });
      setStatus({ text: "確認しました。結果・保存した根拠を表示しています。", error: false });
      await loadHistory();
    } catch (error) {
      setStatus({ text: `要確認: ${(error as Error).message}`, error: true });
    } finally {
      setBusy(false);
    }
  };

  const renderNode = (node: Node, index: number): ReactNode => {
    if ("children" in node) {
      return (
        <label className="wide" key={`${node.key}-${index}`}>
          {label(node.key)}
          <div className="fields">{node.children.map(renderNode)}</div>
        </label>
      );
    }
    const id = JSON.stringify(node.path);
    const value = values[id] ?? "";
    const set = (next: string) => setValues((current) => ({ ...current, [id]: next }));
    let input: ReactNode;
    if (node.kind === "array" || node.kind === "textarea") {
      input = <textarea value={value} onChange={(event) => set(event.target.value)} />;
    } else if (node.kind === "boolean") {
      input = (
        <select value={value} onChange={(event) => set(event.target.value)}>
          <option value="true">はい</option>
          <option value="false">いいえ</option>
        </select>
      );
    } else if (node.kind === "file") {
      input = (
        <input
          type="file"
          accept=".xlsx"
          onChange={(event) => setFiles((current) => ({ ...current, [id]: event.target.files?.[0] }))}
        />
      );
    } else if (node.kind === "select") {
      input = (
        <select value={value} onChange={(event) => set(event.target.value)}>
          {node.options!.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );
    } else {
      input = (
        <input
          type={node.kind === "number" ? "number" : "text"}
          step="any"
          value={value}
          onChange={(event) => set(event.target.value)}
        />
      );
    }
    return (
      <label className={node.wide ? "wide" : undefined} key={id}>
        {label(node.key)}
        {input}
      </label>
    );
  };

  return (
    <div className="sys-items items-ideas">
      <header>
        <Link href="/" className="items-home-link">
          ← トップへ戻る
        </Link>
        {" ・ "}
        <Link href="/items" className="items-home-link">
          統合ワークスペースへ
        </Link>
        <p className="items-brand">
          材料台帳 <span className="tag">Simulator · すべて架空値</span>
        </p>
        <p>部品・塗料・溶剤・消耗品の価格と、見積もりに使った根拠を残す。</p>
      </header>
      <div className="layout">
        <aside aria-label="30案の選択">
          <div className="count">{count}</div>
          <nav>
            {specs.map((spec) => (
              <button
                type="button"
                key={spec.idea_id}
                className={`idea${active?.idea_id === spec.idea_id ? " active" : ""}`}
                onClick={() => select(spec)}
              >
                <span>{spec.idea_id}</span>
                {spec.title}
              </button>
            ))}
          </nav>
        </aside>
        <main>
          <span className="pill">{active?.idea_id}</span>
          <h1>{active ? active.title : "材料の道具を選ぶ"}</h1>
          <p className="description">{active?.description}</p>
          <section>
            <h2>入力と確認</h2>
            <p className="help">
              例示値は実価格ではありません。承認者の入力は人による確認の記録です。PDF・OCR・卸接続は読取候補を使うシミュレーションです。
            </p>
            <form onSubmit={onSubmit} key={formKey}>
              <div className="fields">{active ? buildFields(active.defaults).map(renderNode) : null}</div>
              <button className="submit" type="submit" disabled={busy}>
                確認して実行
              </button>
              <button type="button" className="secondary" onClick={() => active && select(active)}>
                架空の入力例に戻す
              </button>
            </form>
            <div className={`status-line${status.error ? " error" : ""}`} role="status">
              {status.text}
            </div>
          </section>
          <section>
            <h2>結果・保存した根拠</h2>
            <div className="result">
              {result ? (
                <ValueTable value={result.value} />
              ) : (
                <p className="blank">実行結果がここに表示されます。未確認の価格は0円にせず、確認が必要な項目を表示します。</p>
              )}
            </div>
          </section>
          <section>
            <h2>保存済み価格版</h2>
            <button
              className="secondary"
              type="button"
              onClick={() => loadHistory().catch((error) => setStatus({ text: (error as Error).message, error: false }))}
            >
              台帳を再表示
            </button>
            <div className="result">{history && <ValueTable value={history.value} />}</div>
          </section>
        </main>
      </div>
      <footer>単位・価格区分・期限を揃えて確認。過去の見積価格は保存時点のまま保持。外部サービスへの通信は行いません。</footer>
    </div>
  );
}
