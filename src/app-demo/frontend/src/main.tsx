import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import ProfitDashboard from "./ProfitDashboard";
import CasesDashboard, {
  EstimateCase,
  caseRequest,
  caseFields,
  caseStatuses,
} from "./CasesDashboard";

type Vehicle = {
  id: string;
  maker: string;
  model: string;
  model_code: string;
  years: number[];
  grades: string[];
  source_name: string;
  note: string;
  source_url?: string | null;
  retrieved_at?: string;
  length_mm?: number | null;
  width_mm?: number | null;
  height_mm?: number | null;
  powertrain?: string | null;
};
type Job = { id: string; category: string; name: string; description: string };
type Source = {
  id: string;
  source_title: string;
  labor_price: number | null;
  parts_price: number | null;
  total_price: number | null;
  tax_included: boolean | null;
  tax_rate?: number | null;
  mode?: "simulator" | "live";
  source_url?: string | null;
  evidence?: string;
  published_at?: string | null;
  normalized_labor: number | null;
  vehicle_match_level: string;
  work_conditions: string;
  retrieved_at: string;
};
type Draft = {
  job_id: string;
  selected_source_ids: string[];
  labor_price: number;
  parts_price: number;
  conditions: string;
  adjustment_reason: string;
};
type SavedItem = Draft & {
  name: string;
  calculated_labor_price: number | null;
  sources: Source[];
};
type Saved = {
  case_id: string;
  mode?: "simulator" | "live";
  research_id?: string | null;
  winter_conditions?: string[];
  search_suggestions?: string;
  id: string;
  created_at: string;
  vehicle: Vehicle;
  year: number;
  grade: string;
  items: SavedItem[];
  notes: string;
  labor_total: number;
  parts_total: number;
  tax_amount: number;
  total_amount: number;
};
type WebResult = {
  research_id: string;
  sources: Record<string, Source[]>;
  warnings: string[];
  cached: boolean;
  search_suggestions: string;
};
function ResearchNotes({ result }: { result: WebResult | null }) {
  if (!result) return null;
  return (
    <div className="web-notes" role="status">
      <p>
        {result.cached
          ? "24時間以内の調査結果を再利用しました。"
          : "Web検索の結果です。"}
      </p>
      {result.warnings.map((warning) => (
        <p key={warning}>{warning}</p>
      ))}
      {result.search_suggestions && (
        <iframe
          title="Google検索の関連候補"
          sandbox="allow-popups allow-popups-to-escape-sandbox"
          srcDoc={result.search_suggestions}
          referrerPolicy="no-referrer"
        />
      )}
    </div>
  );
}
const taxLabel = (included: boolean | null) =>
  included === null ? "税区分不明" : included ? "税込" : "税抜";
const yen = (n: number) =>
  new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY" }).format(
    n,
  );
const date = (s: string) =>
  new Date(s).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" });
function median(sources: Source[], ids: string[]) {
  const values = sources
    .filter((s) => ids.includes(s.id) && s.normalized_labor !== null)
    .map((s) => s.normalized_labor!)
    .sort((a, b) => a - b);
  return values.length
    ? Math.floor(
        (values[Math.floor((values.length - 1) / 2)] +
          values[Math.floor(values.length / 2)]) /
          2,
      )
    : null;
}
async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    "/api" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "入力内容を確認してください。金額は0〜10,000,000円の整数で入力します。",
    );
  }
  return response.json();
}
function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, React.ReactNode> = {
    wrench: (
      <path d="m14 6 4 4 3-3a6 6 0 0 1-8 8L6 22l-4-4 7-7a6 6 0 0 1 8-8z" />
    ),
    search: (
      <>
        <circle cx="10" cy="10" r="6" />
        <path d="m15 15 5 5" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    car: (
      <>
        <path d="m3 10 3-6h12l3 6v9h-3v-3H6v3H3zM3 10h18" />
        <path d="M6 13h2m8 0h2" />
      </>
    ),
    history: (
      <>
        <path d="M3 10a9 9 0 1 1 2 8M3 4v6h6M12 7v5l3 2" />
      </>
    ),
    save: (
      <>
        <path d="M4 3h13l4 4v14H3V3zM7 3v6h10V3M7 21v-7h10v7" />
      </>
    ),
    plus: <path d="M12 4v16M4 12h16" />,
    close: <path d="m5 5 14 14M19 5 5 19" />,
    chevron: <path d="m9 5 7 7-7 7" />,
    info: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v6m0-10v1" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] || paths.wrench}
    </svg>
  );
}
function CarDrawing() {
  return (
    <svg
      className="car-drawing"
      viewBox="0 0 510 160"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M22 119H491M87 28h335M87 22v12m335-12v12"
        stroke="#8aacc7"
        strokeDasharray="4 5"
      />
      <path
        d="m48 103 8-36 47-9 61-38h132l76 39 74 14 12 32-23 13h-25a33 33 0 0 0-66 0H161a33 33 0 0 0-66 0H61z"
        fill="#e9f1f9"
        stroke="#35628b"
        strokeWidth="2.5"
      />
      <path
        d="m119 59 53-30h52v30zm117-30h57l53 30H236z"
        fill="#bfd5e8"
        stroke="#35628b"
        strokeWidth="2"
      />
      <path
        d="M233 64v44m112-39 14 39M174 72h20m60 0h20M64 75h32l-6 13H61m344-9h27l7 13h-34"
        stroke="#35628b"
        strokeWidth="2"
      />
      <circle
        cx="128"
        cy="117"
        r="26"
        fill="#fafcfe"
        stroke="#35628b"
        strokeWidth="3"
      />
      <circle cx="128" cy="117" r="14" stroke="#8aacc7" strokeWidth="2" />
      <circle
        cx="377"
        cy="117"
        r="26"
        fill="#fafcfe"
        stroke="#35628b"
        strokeWidth="3"
      />
      <circle cx="377" cy="117" r="14" stroke="#8aacc7" strokeWidth="2" />
    </svg>
  );
}
const steps = [
  "車両を選ぶ",
  "作業を選ぶ",
  "参考金額を比較",
  "金額を確定・保存",
];
const winterOptions = [
  {
    id: "salt_roads",
    label: "融雪剤を使う道路での走行",
    detail: "下回りの状態を確認するための相談条件",
  },
  {
    id: "rust_check",
    label: "サビ・ボルトの固着を現車で確認",
    detail: "追加工程の有無は作業前に担当者が確認",
  },
  {
    id: "cold_start",
    label: "寒い日の始動・補機バッテリーを相談",
    detail: "交換の要否は点検後に確認",
  },
];
function WinterSummary({ conditions }: { conditions: string[] }) {
  if (!conditions.length) return null;
  return (
    <div className="winter-summary">
      <strong>雪国の確認条件</strong>
      <p>
        {winterOptions
          .filter((o) => conditions.includes(o.id))
          .map((o) => o.label)
          .join(" / ")}
      </p>
      <small>追加作業・追加工賃は現車確認後に相談</small>
    </div>
  );
}
function App() {
  const [view, setView] = useState<"estimate" | "profit">("estimate");
  const [estimateScreen, setEstimateScreen] = useState<"cases" | "editor">(
    "cases",
  );
  const [currentCase, setCurrentCase] = useState<EstimateCase | null>(null);
  const [caseRevision, setCaseRevision] = useState(0);
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<"simulator" | "live">("simulator");
  const [geminiReady, setGeminiReady] = useState(false);
  const [legacyWinterConditions, setLegacyWinterConditions] = useState<
    string[]
  >([]);
  const [webPrices, setWebPrices] = useState<WebResult | null>(null);
  const [researchId, setResearchId] = useState<string | null>(null);
  useEffect(() => {
    api<{ gemini_configured: boolean }>("/config")
      .then((c) => setGeminiReady(c.gemini_configured))
      .catch(() => {});
  }, []);
  const [query, setQuery] = useState("FL4");
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [year, setYear] = useState("");
  const [grade, setGrade] = useState("");
  const [jobIds, setJobIds] = useState<string[]>([]);
  const [category, setCategory] = useState("すべて");
  const [sources, setSources] = useState<Record<string, Source[]>>({});
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<Saved | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyQuery, setHistoryQuery] = useState("");
  const [history, setHistory] = useState<Saved[]>([]);
  const [detail, setDetail] = useState<Saved | null>(null);
  const [manual, setManual] = useState(true);
  const [manualData, setManualData] = useState({
    maker: "",
    model: "",
    model_code: "",
    year: "2023",
    grade: "",
  });
  useEffect(() => {
    api<Job[]>("/repair-jobs")
      .then(setJobs)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      api<Vehicle[]>("/vehicles?query=" + encodeURIComponent(query))
        .then((v) => {
          if (active) setVehicles(v);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 180);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query]);
  useEffect(() => {
    if (!historyOpen) return;
    let active = true;
    api<Saved[]>("/estimates?query=" + encodeURIComponent(historyQuery))
      .then((h) => {
        if (active) setHistory(h);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [historyOpen, historyQuery]);
  useEffect(() => {
    if (!historyOpen) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setHistoryOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const old = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = old;
      document.removeEventListener("keydown", onKey);
      previousFocus?.focus();
    };
  }, [historyOpen]);
  const chosenJobs = jobs.filter((j) => jobIds.includes(j.id));
  const labor = drafts.reduce((a, i) => a + i.labor_price, 0);
  const parts = drafts.reduce((a, i) => a + i.parts_price, 0);
  const tax = Math.floor((labor + parts) / 10);
  const total = labor + parts + tax;
  const updateDraft = (job: string, patch: Partial<Draft>) =>
    setDrafts((d) => d.map((i) => (i.job_id === job ? { ...i, ...patch } : i)));
  function chooseVehicle(v: Vehicle) {
    setManual(false);
    setVehicle(v);
    setLegacyWinterConditions([]);
    setYear("");
    setGrade("");
    setSources({});
    setDrafts([]);
    setResearchId(null);
    setWebPrices(null);
    setSaved(null);
    setError("");
  }
  function switchMode(next: "simulator" | "live") {
    setMode(next);
    setSources({});
    setDrafts([]);
    setWebPrices(null);
    setResearchId(null);
    setError("");
  }
  async function research() {
    if (!vehicle) return;
    setBusy(true);
    setError("");
    setLegacyWinterConditions([]);
    try {
      const response = await api<Record<string, Source[]> | WebResult>(
        "/price-research",
        {
          vehicle_id: vehicle.id,
          year: Number(year),
          grade,
          job_ids: jobIds,
          mode,
        },
      );
      const web = mode === "live" ? (response as WebResult) : null;
      const result = web ? web.sources : (response as Record<string, Source[]>);
      setWebPrices(web);
      setResearchId(web?.research_id ?? null);
      setSources(result);
      setDrafts(
        jobIds.map((id) => {
          const selected = result[id]
            .filter((s) => mode === "simulator" && s.normalized_labor !== null)
            .map((s) => s.id);
          const old =
            mode === "simulator"
              ? drafts.find((d) => d.job_id === id)
              : undefined;
          return old
            ? { ...old, selected_source_ids: selected }
            : {
                job_id: id,
                selected_source_ids: selected,
                labor_price: median(result[id], selected) ?? 0,
                parts_price: 0,
                conditions: jobs.find((j) => j.id === id)!.description,
                adjustment_reason: "",
              };
        }),
      );
      setStep(2);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function toggleSource(job: string, source: string) {
    const draft = drafts.find((d) => d.job_id === job)!;
    const ids = draft.selected_source_ids.includes(source)
      ? draft.selected_source_ids.filter((s) => s !== source)
      : [...draft.selected_source_ids, source];
    updateDraft(job, {
      selected_source_ids: ids,
      labor_price: median(sources[job], ids) ?? 0,
      adjustment_reason: "",
    });
  }
  const validMoney = drafts.every(
    (i) =>
      Number.isInteger(i.labor_price) &&
      i.labor_price >= 0 &&
      i.labor_price <= 10000000 &&
      Number.isInteger(i.parts_price) &&
      i.parts_price >= 0 &&
      i.parts_price <= 10000000,
  );
  const validReasons = drafts.every((i) => {
    const calculated = median(sources[i.job_id] ?? [], i.selected_source_ids);
    return (
      (calculated !== null && calculated === i.labor_price) ||
      i.adjustment_reason.trim().length > 0
    );
  });
  async function save() {
    if (!vehicle || !currentCase) return;
    setBusy(true);
    setError("");
    try {
      setSaved(
        await api<Saved>("/estimates", {
          case_id: currentCase.id,
          mode,
          research_id: researchId,
          vehicle_id: vehicle.id,
          year: Number(year),
          grade,
          winter_conditions: legacyWinterConditions,
          items: drafts,
          notes,
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function registerManual() {
    setBusy(true);
    setError("");
    try {
      const v = await api<Vehicle>("/vehicles", {
        ...manualData,
        year: Number(manualData.year),
      });
      chooseVehicle(v);
      setYear(manualData.year);
      setGrade(manualData.grade.trim());
      setManual(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function reset() {
    setStep(0);
    setVehicle(null);
    setWebPrices(null);
    setResearchId(null);
    setYear("");
    setGrade("");
    setJobIds([]);
    setLegacyWinterConditions([]);
    setDrafts([]);
    setSources({});
    setSaved(null);
    setNotes("");
    setError("");
  }
  function showCases() {
    setEstimateScreen("cases");
    setCaseRevision((n) => n + 1);
  }
  async function openCase(c: EstimateCase) {
    if (
      currentCase?.id !== c.id &&
      !saved &&
      (vehicle || drafts.length) &&
      !window.confirm(
        "別の案件を開くと、現在入力中の見積もりは破棄されます。続けますか？",
      )
    )
      return;
    const estimate = c.latest_estimate_id
      ? await api<Saved>("/estimates/" + c.latest_estimate_id)
      : null;
    const updated =
      c.status === "unestimated"
        ? await caseRequest<EstimateCase>("/" + c.id, "PUT", {
            ...caseFields(c),
            status: "estimating",
          })
        : c;
    if (currentCase?.id !== c.id || saved) {
      reset();
      if (estimate) loadEstimate(estimate, false);
    }
    setCurrentCase(updated);
    setEstimateScreen("editor");
  }
  async function reuse(item: Saved) {
    if (
      !saved &&
      drafts.length &&
      !window.confirm(
        "保存済みの条件を開くと、現在入力中の見積もりは破棄されます。続けますか？",
      )
    )
      return;
    try {
      const c = await caseRequest<EstimateCase>("", "POST", {
        title: item.items
          .map((i) => i.name)
          .join("・")
          .slice(0, 120),
        vehicle_label: `${item.vehicle.maker} ${item.vehicle.model} / ${item.vehicle.model_code}`,
        status: "estimating",
      });
      setCurrentCase(c);
      loadEstimate(item);
      setEstimateScreen("editor");
      setView("estimate");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function loadEstimate(item: Saved, copy = true) {
    setMode(item.mode ?? "simulator");
    setLegacyWinterConditions(item.winter_conditions ?? []);
    setResearchId(item.research_id ?? null);
    setWebPrices(null);
    setVehicle(item.vehicle);
    setYear(String(item.year));
    setGrade(item.grade);
    setJobIds(item.items.map((i) => i.job_id));
    setSources(
      Object.fromEntries(item.items.map((i) => [i.job_id, i.sources])),
    );
    setDrafts(
      item.items.map((i) => ({
        job_id: i.job_id,
        selected_source_ids: i.selected_source_ids,
        labor_price: i.labor_price,
        parts_price: i.parts_price,
        conditions: i.conditions,
        adjustment_reason: i.adjustment_reason,
      })),
    );
    setNotes(
      (copy
        ? `再利用元: ${item.id} / 保存日時: ${date(item.created_at)}\n${item.notes}`
        : item.notes
      ).slice(0, 2000),
    );
    setSaved(null);
    setStep(3);
    setHistoryOpen(false);
    setError("");
  }
  function navigate(s: number) {
    setError("");
    setStep(s);
  }
  return (
    <>
      <header
        className="app-header"
        data-view={view}
        data-screen={estimateScreen}
      >
        <a className="brand" href="/" aria-label="整備見積ワークベンチ ホーム">
          <span className="brand-mark">
            <Icon name="wrench" size={23} />
          </span>
          <span>
            整備見積<span className="brand-sub">ワークベンチ</span>
          </span>
        </a>
        <nav className="view-tabs" aria-label="画面切り替え">
          <button
            aria-pressed={view === "estimate"}
            onClick={() => {
              setView("estimate");
              showCases();
            }}
          >
            見積もり
          </button>
          <button
            aria-pressed={view === "profit"}
            onClick={() => setView("profit")}
          >
            売上・利益
          </button>
        </nav>
        <div className="header-right" hidden={view !== "estimate"}>
          <span className="mode-tag">
            <span />
            {mode === "live" ? "Gemini 工賃調査" : "Simulator"}
          </span>
          <button
            className="history-button"
            onClick={() => {
              setHistoryOpen(true);
              setDetail(null);
            }}
          >
            <Icon name="history" />
            保存した見積もり
          </button>
        </div>
      </header>
      <div hidden={view !== "estimate" || estimateScreen !== "cases"}>
        <CasesDashboard revision={caseRevision} onOpen={openCase} />
      </div>
      <div className="demo-banner">
        <Icon name="info" size={16} />
        <span>
          {mode === "live"
            ? "工賃調査モード：入力した型式・作業条件をもとにAIが参考料金を調べます。出典を確認してください。"
            : "デモモード：車両情報・参考価格はサンプルです。実価格・実車への適合を保証しません。"}
        </span>
        <span className="offline-badge">
          {mode === "live"
            ? "gemini-2.5-flash / 無料枠プロジェクトで使用"
            : "外部API接続なし"}
        </span>
      </div>
      <div className="workspace">
        <aside className="workflow">
          <p className="workflow-title">見積もりの作成</p>
          <nav aria-label="見積もり作成の手順">
            {steps.map((label, i) => (
              <button
                key={label}
                className={`step-button ${step === i ? "current" : ""} ${step > i ? "complete" : ""}`}
                disabled={i > step || !!saved}
                onClick={() => navigate(i)}
                aria-current={step === i ? "step" : undefined}
              >
                <span className="step-number">
                  {step > i ? <Icon name="check" size={16} /> : i + 1}
                </span>
                <span>
                  {label}
                  <small>
                    {
                      [
                        "型式・年式・仕様",
                        "修理内容と条件",
                        "採用する根拠を選択",
                        "確認して記録",
                      ][i]
                    }
                  </small>
                </span>
              </button>
            ))}
          </nav>
          <div className="workflow-note">
            <Icon name="wrench" />
            <p>
              判断の根拠を、
              <br />
              次の見積もりへ。
            </p>
            <small>入力した条件と採用した参考情報を一緒に保存します。</small>
          </div>
          <div className="local-label">
            <span />
            ローカルSQLiteに保存
          </div>
        </aside>
        <main className="main-content">
          {currentCase && (
            <div className="case-editor-bar">
              <button
                className="secondary-button"
                disabled={busy}
                onClick={showCases}
              >
                案件一覧に戻る
              </button>
              <div className="case-editor-info">
                <strong>{currentCase.title}</strong>
                <span className="case-id">{currentCase.id}</span>
              </div>
              <span
                className={`case-status ${saved ? "completed" : currentCase.status}`}
              >
                {saved ? "完了" : caseStatuses[currentCase.status]}
              </span>
            </div>
          )}
          <div className="page-heading">
            <div>
              <p className="step-caption">手順 {step + 1} / 4</p>
              <h1>{saved ? "見積もりを保存しました" : steps[step]}</h1>
              <p className="muted">
                {saved
                  ? "金額と、その判断に使った根拠を記録しました。"
                  : [
                      "車検証を見ながら型式・年式・仕様を入力してください。AIによる型式特定は行いません。",
                      "今回の作業を選び、金額を左右する条件を確認します。",
                      "比較できる工賃を採用し、参考金額を確認します。",
                      "部品代と工賃を確認・調整し、見積もりを記録します。",
                    ][step]}
              </p>
            </div>
            <span className="draft-badge">
              {saved ? "保存済み" : "新規見積もり"}
            </span>
          </div>
          {error && (
            <div className="error-message" role="alert">
              <Icon name="info" />
              {error}
              <button onClick={() => setError("")} aria-label="エラーを閉じる">
                <Icon name="close" size={16} />
              </button>
            </div>
          )}
          {step === 1 && (
            <div className="mode-selector" role="group" aria-label="調査モード">
              <button
                className={mode === "simulator" ? "active" : ""}
                disabled={busy}
                aria-pressed={mode === "simulator"}
                onClick={() => switchMode("simulator")}
              >
                Simulator（架空データ）
              </button>
              <button
                className={mode === "live" ? "active" : ""}
                disabled={busy}
                aria-pressed={mode === "live"}
                onClick={() => switchMode("live")}
              >
                AIで工賃を調査（Gemini）
              </button>
            </div>
          )}
          {step >= 1 && mode === "live" && !geminiReady && (
            <div className="info-strip">
              APIキーが未設定です。src/app-demo/.env の GEMINI_API_KEY
              に設定してバックエンドを再起動してください。Simulatorはそのまま使えます。
            </div>
          )}
          {busy && mode === "live" && (
            <div className="info-strip" role="status">
              公開資料を検索・整理しています。完了まで少し時間がかかります。
            </div>
          )}
          <div className="content-grid">
            <section className="editor">
              {step === 0 && (
                <>
                  <div className="panel search-panel">
                    <h2>
                      <Icon name="search" />
                      車検証の情報を入力・確認
                    </h2>
                    <label htmlFor="vehicle-search" className="field-label">
                      登録済み車両を検索（外部通信なし）
                    </label>
                    <div className="search-input">
                      <Icon name="search" />
                      <input
                        id="vehicle-search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="例：シビック、FL4"
                        autoComplete="off"
                      />
                    </div>
                    <div className="search-meta">
                      <span>
                        {vehicles.length}件の登録済み車両（サンプルを含む）
                      </span>
                      <span>型式とVIN・車台番号は別の識別子です</span>
                    </div>
                    <div className="vehicle-results">
                      {vehicles.map((v) => (
                        <button
                          key={v.id}
                          className={`vehicle-result ${vehicle?.id === v.id ? "selected" : ""}`}
                          onClick={() => chooseVehicle(v)}
                        >
                          <span className="vehicle-icon">
                            <Icon name="car" size={26} />
                          </span>
                          <span className="vehicle-result-name">
                            <small>{v.maker}</small>
                            <strong>{v.model}</strong>
                            <span>{v.grades[0]}</span>
                          </span>
                          <span className="model-code">{v.model_code}</span>
                          <span className="selection-dot">
                            {vehicle?.id === v.id && (
                              <Icon name="check" size={13} />
                            )}
                          </span>
                        </button>
                      ))}
                      {vehicles.length === 0 && (
                        <p className="empty">
                          候補が見つかりません。車両情報を手入力できます。
                        </p>
                      )}
                    </div>
                    <button
                      className="text-button"
                      onClick={() => setManual(!manual)}
                    >
                      <Icon name="plus" size={16} />
                      {manual ? "手入力を閉じる" : "車両情報を手入力する"}
                    </button>
                    {manual && (
                      <form
                        className="manual-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          void registerManual();
                        }}
                      >
                        <p className="muted">
                          未確認の車両として、SQLiteに暫定登録します。
                        </p>
                        <div className="field-grid">
                          {(
                            [
                              ["maker", "メーカー"],
                              ["model", "車種名"],
                              ["model_code", "型式"],
                              ["year", "年式"],
                              ["grade", "グレード・仕様"],
                            ] as const
                          ).map(([key, label]) => (
                            <label key={key}>
                              {label}
                              <input
                                required
                                maxLength={key === "model_code" ? 40 : 80}
                                type={key === "year" ? "number" : "text"}
                                min={key === "year" ? 1900 : undefined}
                                max={key === "year" ? 2100 : undefined}
                                value={manualData[key]}
                                onChange={(e) =>
                                  setManualData({
                                    ...manualData,
                                    [key]: e.target.value,
                                  })
                                }
                              />
                            </label>
                          ))}
                        </div>
                        <button className="primary-button" disabled={busy}>
                          この車両を暫定登録
                        </button>
                      </form>
                    )}
                  </div>
                  {vehicle ? (
                    <div className="panel vehicle-details">
                      <div className="panel-heading">
                        <h2>年式・仕様を確認</h2>
                        <span className="small-tag">{vehicle.source_name}</span>
                      </div>
                      <div className="field-grid">
                        <label>
                          年式
                          <select
                            aria-label="年式"
                            value={year}
                            onChange={(e) => setYear(e.target.value)}
                          >
                            <option value="">年式を選択</option>
                            {vehicle.years.map((y) => (
                              <option key={y} value={y}>
                                {y}年
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          グレード・仕様
                          <select
                            aria-label="グレード・仕様"
                            value={grade}
                            onChange={(e) => setGrade(e.target.value)}
                          >
                            <option value="">仕様を選択</option>
                            {vehicle.grades.map((g) => (
                              <option key={g}>{g}</option>
                            ))}
                          </select>
                        </label>
                      </div>
                      <div className="specs">
                        <span>
                          全長
                          <strong>
                            {vehicle.length_mm
                              ? `${vehicle.length_mm} mm`
                              : "未確認"}
                          </strong>
                        </span>
                        <span>
                          全幅
                          <strong>
                            {vehicle.width_mm
                              ? `${vehicle.width_mm} mm`
                              : "未確認"}
                          </strong>
                        </span>
                        <span>
                          全高
                          <strong>
                            {vehicle.height_mm
                              ? `${vehicle.height_mm} mm`
                              : "未確認"}
                          </strong>
                        </span>
                        <span>
                          駆動方式
                          <strong>{vehicle.powertrain || "未確認"}</strong>
                        </span>
                      </div>
                      <p className="note">
                        <Icon name="info" size={16} />
                        {vehicle.note}
                      </p>
                      {vehicle.source_url && (
                        <a
                          className="source-link"
                          href={vehicle.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          車両情報の出典を確認
                        </a>
                      )}
                    </div>
                  ) : (
                    <div className="vehicle-placeholder">
                      <CarDrawing />
                      <p>まずは、見積もりする車両を選んでください。</p>
                    </div>
                  )}
                  <div className="actions">
                    <span className="muted">年式・仕様の選択が必要です</span>
                    <button
                      className="primary-button"
                      disabled={!vehicle || !year || !grade}
                      onClick={() => navigate(1)}
                    >
                      作業を選ぶ
                      <Icon name="arrow" size={18} />
                    </button>
                  </div>
                </>
              )}
              {step === 1 && (
                <>
                  <div className="panel">
                    <h2>
                      <Icon name="wrench" />
                      作業内容
                    </h2>
                    <div
                      className="categories"
                      role="group"
                      aria-label="作業カテゴリー"
                    >
                      {["すべて", ...new Set(jobs.map((j) => j.category))].map(
                        (c) => (
                          <button
                            key={c}
                            className={category === c ? "active" : ""}
                            aria-pressed={category === c}
                            onClick={() => setCategory(c)}
                          >
                            {c}
                          </button>
                        ),
                      )}
                    </div>
                    <div className="jobs-list">
                      {jobs
                        .filter(
                          (j) =>
                            category === "すべて" || category === j.category,
                        )
                        .map((j) => (
                          <label
                            key={j.id}
                            className={`job-option ${jobIds.includes(j.id) ? "selected" : ""}`}
                          >
                            <input
                              type="checkbox"
                              checked={jobIds.includes(j.id)}
                              onChange={(e) => {
                                setJobIds((ids) =>
                                  e.target.checked
                                    ? [...ids, j.id]
                                    : ids.filter((id) => id !== j.id),
                                );
                              }}
                            />
                            <span>
                              <strong>{j.name}</strong>
                              <small>{j.description}</small>
                            </span>
                            <span className="job-category">{j.category}</span>
                          </label>
                        ))}
                    </div>
                  </div>
                  <div className="info-strip">
                    <Icon name="info" />
                    <span>
                      複数作業を選択できます。重複する工程の工賃は自動控除しません。
                    </span>
                  </div>
                  <div className="actions">
                    <button
                      className="secondary-button"
                      onClick={() => navigate(0)}
                    >
                      車両選択へ戻る
                    </button>
                    <button
                      className="primary-button"
                      disabled={
                        !jobIds.length ||
                        busy ||
                        (mode === "live" && !geminiReady)
                      }
                      onClick={() => void research()}
                    >
                      {busy ? "工賃を調査中…" : "参考価格を比較する"}
                      <Icon name="arrow" size={18} />
                    </button>
                  </div>
                </>
              )}
              {step === 2 && (
                <>
                  <div className="info-strip">
                    <Icon name="info" />
                    <span>
                      {mode === "live"
                        ? "Web料金はAI抽出・未確認です。出典を確認してから採用してください。工賃内訳・税区分・一致条件が不明な候補は比較対象外です。"
                        : "すべて架空の価格です。税込の工賃は税抜に換算し、採用した工賃の中央値を算出します。"}
                    </span>
                  </div>
                  <ResearchNotes result={webPrices} />
                  {chosenJobs.map((j) => {
                    const draft = drafts.find((i) => i.job_id === j.id)!;
                    const calculated = median(
                      sources[j.id],
                      draft.selected_source_ids,
                    );
                    return (
                      <div className="comparison-group" key={j.id}>
                        <div className="comparison-heading">
                          <h2>{j.name}</h2>
                          <span>参考候補 {sources[j.id].length}件</span>
                        </div>
                        {sources[j.id].length === 0 && (
                          <div className="info-strip">
                            料金の根拠が見つかりませんでした。金額確定画面で工賃と理由を手入力できます。
                          </div>
                        )}
                        <div className="source-grid">
                          {sources[j.id].map((s) => {
                            const selected = draft.selected_source_ids.includes(
                              s.id,
                            );
                            return (
                              <article
                                className={`source-card ${selected ? "adopted" : ""} ${s.normalized_labor === null ? "incomparable" : ""}`}
                                key={s.id}
                              >
                                <div className="source-top">
                                  <span className="small-tag">
                                    {s.mode === "live"
                                      ? "AI抽出・要確認"
                                      : "架空データ"}
                                  </span>
                                  <label className="adopt-toggle">
                                    <input
                                      type="checkbox"
                                      checked={selected}
                                      disabled={s.normalized_labor === null}
                                      onChange={() => toggleSource(j.id, s.id)}
                                    />
                                    {selected
                                      ? "採用"
                                      : s.normalized_labor === null
                                        ? "比較対象外"
                                        : "除外"}
                                  </label>
                                </div>
                                <h3>{s.source_title}</h3>
                                <p className="source-price-label">
                                  {s.labor_price === null
                                    ? "工賃・部品の総額"
                                    : "工賃"}
                                  <span>
                                    {taxLabel(s.tax_included)}
                                    {s.mode === "live" &&
                                    s.tax_included &&
                                    s.tax_rate == null
                                      ? "（税率不明）"
                                      : ""}
                                  </span>
                                </p>
                                <p className="source-price">
                                  {s.labor_price === null &&
                                  s.total_price === null
                                    ? "金額不明"
                                    : yen(s.labor_price ?? s.total_price!)}
                                </p>
                                <p className="source-parts">
                                  部品代{" "}
                                  {s.parts_price === null
                                    ? "別途・金額不明"
                                    : yen(s.parts_price) +
                                      (s.total_price !== null
                                        ? "（総額に含む）"
                                        : "")}
                                </p>
                                <div className="source-metadata">
                                  <span
                                    className={
                                      s.normalized_labor === null
                                        ? "warning-text"
                                        : ""
                                    }
                                  >
                                    {s.vehicle_match_level}
                                  </span>
                                  <p>{s.work_conditions}</p>
                                  {s.tax_included &&
                                    s.normalized_labor !== null && (
                                      <p>
                                        税抜換算工賃：{yen(s.normalized_labor!)}
                                      </p>
                                    )}
                                  <small>
                                    情報源{" "}
                                    {s.mode === "live"
                                      ? "Gemini Web調査"
                                      : "simulator"}
                                    <br />
                                    参照日{" "}
                                    {s.mode === "live"
                                      ? date(s.retrieved_at)
                                      : s.retrieved_at}
                                    <br />
                                    {s.mode === "live"
                                      ? "掲載日 " + (s.published_at || "不明")
                                      : "サンプル／実価格ではない"}
                                  </small>
                                  {s.source_url && (
                                    <a
                                      className="source-link"
                                      href={s.source_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                    >
                                      出典ページを確認
                                    </a>
                                  )}
                                  {s.evidence && (
                                    <p className="source-evidence">
                                      抽出根拠：{s.evidence}
                                    </p>
                                  )}
                                </div>
                              </article>
                            );
                          })}
                        </div>
                        <div className="median-strip">
                          <span>
                            採用した工賃の中央値 <small>税抜</small>
                          </span>
                          <strong>
                            {calculated === null ? "算出不可" : yen(calculated)}
                          </strong>
                          <span>
                            {calculated === null
                              ? "金額確定画面で手入力してください"
                              : draft.selected_source_ids.length +
                                "件の工賃を採用"}
                          </span>
                        </div>
                        <label className="condition-field">
                          作業条件・追加事項
                          <textarea
                            maxLength={1000}
                            value={draft.conditions}
                            onChange={(e) =>
                              updateDraft(j.id, { conditions: e.target.value })
                            }
                            rows={2}
                          />
                        </label>
                      </div>
                    );
                  })}
                  <div className="actions">
                    <button
                      className="secondary-button"
                      onClick={() => navigate(1)}
                    >
                      作業選択へ戻る
                    </button>
                    <button
                      className="primary-button"
                      onClick={() => navigate(3)}
                    >
                      金額を確認する
                      <Icon name="arrow" size={18} />
                    </button>
                  </div>
                </>
              )}
              {step === 3 &&
                (saved ? (
                  <div className="panel saved-panel">
                    <span className="success-icon">
                      <Icon name="check" size={30} />
                    </span>
                    <h2>SQLiteに記録しました</h2>
                    <p>
                      {saved.vehicle.maker} {saved.vehicle.model} /{" "}
                      {saved.vehicle.model_code}
                    </p>
                    <strong className="saved-total">
                      {yen(saved.total_amount)}
                    </strong>
                    <p className="muted">
                      見積番号 {saved.id}
                      <br />
                      {date(saved.created_at)}
                    </p>
                    <p className="note">
                      ページを再読み込みしても「保存した見積もり」から確認できます。
                    </p>
                    <div className="saved-actions">
                      <button
                        className="secondary-button"
                        onClick={() => {
                          setDetail(saved);
                          setHistoryOpen(true);
                        }}
                      >
                        保存した内容を見る
                      </button>
                      <button className="primary-button" onClick={showCases}>
                        案件一覧で確認する
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="panel">
                      <div className="panel-heading">
                        <h2>確定する金額</h2>
                        <span className="small-tag">入力金額は税抜</span>
                      </div>
                      {chosenJobs.map((j) => {
                        const d = drafts.find((i) => i.job_id === j.id)!;
                        const calculated = median(
                          sources[j.id],
                          d.selected_source_ids,
                        );
                        const adjusted =
                          calculated === null || calculated !== d.labor_price;
                        return (
                          <div className="final-item" key={j.id}>
                            <h3>{j.name}</h3>
                            <p className="muted">{d.conditions}</p>
                            <p className="reference-note">
                              算出工賃：
                              {calculated === null
                                ? "採用候補なし・手入力が必要です"
                                : yen(calculated) + "（税抜中央値）"}
                            </p>
                            <div className="field-grid">
                              <label>
                                確定工賃（円・税抜）
                                <input
                                  aria-label={j.name + "の確定工賃"}
                                  type="number"
                                  min="0"
                                  max="10000000"
                                  step="1"
                                  required
                                  value={
                                    Number.isNaN(d.labor_price)
                                      ? ""
                                      : d.labor_price
                                  }
                                  onChange={(e) =>
                                    updateDraft(j.id, {
                                      labor_price:
                                        e.target.value === ""
                                          ? NaN
                                          : Number(e.target.value),
                                    })
                                  }
                                />
                              </label>
                              <label>
                                部品代（円・税抜）
                                <input
                                  aria-label={j.name + "の部品代"}
                                  type="number"
                                  min="0"
                                  max="10000000"
                                  step="1"
                                  required
                                  value={
                                    Number.isNaN(d.parts_price)
                                      ? ""
                                      : d.parts_price
                                  }
                                  onChange={(e) =>
                                    updateDraft(j.id, {
                                      parts_price:
                                        e.target.value === ""
                                          ? NaN
                                          : Number(e.target.value),
                                    })
                                  }
                                />
                              </label>
                            </div>
                            <p className="help-text">
                              部品代は手入力です。初期値の0円は、部品が無料という意味ではありません。
                            </p>
                            <label className="condition-field">
                              工賃の手入力・調整理由
                              {adjusted && (
                                <span className="required"> 必須</span>
                              )}
                              <input
                                maxLength={1000}
                                value={d.adjustment_reason}
                                onChange={(e) =>
                                  updateDraft(j.id, {
                                    adjustment_reason: e.target.value,
                                  })
                                }
                                placeholder="例：固着による追加工程を含める"
                              />
                            </label>
                          </div>
                        );
                      })}
                      <label className="condition-field">
                        見積もりメモ
                        <textarea
                          maxLength={2000}
                          rows={3}
                          value={notes}
                          onChange={(e) => setNotes(e.target.value)}
                          placeholder="含まない作業、部品代の確認状況など"
                        />
                      </label>
                    </div>
                    <div className="info-strip">
                      <Icon name="info" />
                      <span>
                        概算は正式な修理費用の保証ではありません。車両適合と作業条件を確認してから金額を確定してください。
                      </span>
                    </div>
                    <div className="actions">
                      <button
                        className="secondary-button"
                        onClick={() => navigate(2)}
                      >
                        候補比較へ戻る
                      </button>
                      <button
                        className="primary-button"
                        disabled={busy || !validMoney || !validReasons}
                        onClick={() => void save()}
                      >
                        <Icon name="save" size={18} />
                        {busy ? "保存中…" : "金額を確定して保存"}
                      </button>
                    </div>
                    {(!validMoney || !validReasons) && (
                      <p className="validation-hint" role="status">
                        {!validMoney
                          ? "工賃・部品代に0〜10,000,000円の整数を入力してください。"
                          : "工賃を手入力・変更した作業には、調整理由を入力してください。"}
                      </p>
                    )}
                  </>
                ))}
            </section>
            <aside className="summary">
              <div className="summary-header">
                <h2>見積もり明細</h2>
                <span>概算</span>
              </div>
              <div className="summary-car">
                <CarDrawing />
                {vehicle ? (
                  <>
                    <small>{vehicle.maker}</small>
                    <h3>
                      {vehicle.model} <span>{vehicle.model_code}</span>
                    </h3>
                    <p>
                      {year ? year + "年" : "年式未選択"} /{" "}
                      {grade || "仕様未選択"}
                    </p>
                  </>
                ) : (
                  <p>車両を選択すると表示されます</p>
                )}
              </div>
              <div className="summary-jobs">
                <h3>
                  作業内容 <span>{chosenJobs.length}件</span>
                </h3>
                {chosenJobs.length ? (
                  chosenJobs.map((j) => (
                    <div key={j.id}>
                      <p>{j.name}</p>
                      <span>
                        {step >= 2
                          ? yen(
                              drafts.find((d) => d.job_id === j.id)
                                ?.labor_price ?? 0,
                            )
                          : "未算出"}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="muted">作業はまだ選択されていません</p>
                )}
              </div>
              <div className="summary-amounts">
                <div>
                  <span>工賃</span>
                  <strong>{step >= 2 && validMoney ? yen(labor) : "—"}</strong>
                </div>
                <div>
                  <span>部品代</span>
                  <strong>{step >= 2 && validMoney ? yen(parts) : "—"}</strong>
                </div>
                <div>
                  <span>
                    消費税 <small>10%</small>
                  </span>
                  <strong>{step >= 2 && validMoney ? yen(tax) : "—"}</strong>
                </div>
                <small>税額の円未満は切り捨て</small>
              </div>
              <div className="summary-total">
                <span>合計（税込）</span>
                <strong>{step >= 2 && validMoney ? yen(total) : "—"}</strong>
              </div>
              <p className="summary-footnote">
                {mode === "live"
                  ? "Web資料による参考概算です。"
                  : "サンプルによる概算です。"}
                <br />
                最終金額は担当者が確認・決定します。
              </p>
            </aside>
          </div>
          <footer className="page-footer">
            <span>当別未来フェス / 自動車整備デモ</span>
            <span>
              参考情報の出所：{mode === "live" ? "Gemini Web調査" : "simulator"}
            </span>
          </footer>
        </main>
      </div>
      {historyOpen && (
        <div
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setHistoryOpen(false);
          }}
        >
          <dialog
            open
            className="history-dialog"
            aria-labelledby="history-title"
            onKeyDown={(e) => {
              if (e.key !== "Tab") return;
              const items = [
                ...e.currentTarget.querySelectorAll<HTMLElement>(
                  "button, input, select, textarea, a[href]",
                ),
              ].filter((el) => !(el as HTMLButtonElement).disabled);
              const first = items[0];
              const last = items[items.length - 1];
              if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last?.focus();
              } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first?.focus();
              }
            }}
          >
            <div className="dialog-header">
              <h2 id="history-title">
                <Icon name="history" />
                保存した見積もり
              </h2>
              <button
                className="icon-button"
                autoFocus
                aria-label="履歴を閉じる"
                onClick={() => setHistoryOpen(false)}
              >
                <Icon name="close" />
              </button>
            </div>
            {detail ? (
              <>
                <button className="text-button" onClick={() => setDetail(null)}>
                  一覧へ戻る
                </button>
                <div className="history-detail">
                  <span className="small-tag">保存当時の条件・参考情報</span>
                  <h3>
                    {detail.vehicle.maker} {detail.vehicle.model} /{" "}
                    {detail.vehicle.model_code}
                  </h3>
                  <p>
                    {detail.year}年 / {detail.grade}
                  </p>
                  <p className="muted">
                    最終更新：{date(detail.created_at)}
                    <br />
                    見積番号 {detail.id} /{" "}
                    {detail.mode === "live" ? "Gemini Web調査" : "simulator"}
                  </p>
                  <WinterSummary conditions={detail.winter_conditions ?? []} />
                  {detail.items.map((i, index) => (
                    <div key={index} className="history-item">
                      <h4>{i.name}</h4>
                      <p>{i.conditions}</p>
                      <div className="history-prices">
                        <span>
                          算出工賃{" "}
                          {i.calculated_labor_price === null
                            ? "算出不可"
                            : yen(i.calculated_labor_price)}
                        </span>
                        <span>確定工賃 {yen(i.labor_price)}</span>
                        <span>部品代 {yen(i.parts_price)}</span>
                      </div>
                      {i.adjustment_reason && (
                        <p>調整理由：{i.adjustment_reason}</p>
                      )}
                      <details>
                        <summary>参照した根拠・採用状況</summary>
                        {i.sources.map((s) => (
                          <p key={s.id}>
                            {i.selected_source_ids.includes(s.id)
                              ? "採用"
                              : "除外"}{" "}
                            / {s.source_title} /{" "}
                            {s.labor_price !== null
                              ? "工賃 " + yen(s.labor_price)
                              : "総額 " + yen(s.total_price ?? 0)}
                            （{taxLabel(s.tax_included)}
                            {s.mode === "live" &&
                            s.tax_included &&
                            s.tax_rate == null
                              ? "（税率不明）"
                              : ""}
                            ）<br />
                            {s.work_conditions}
                            <br />
                            {s.mode === "live"
                              ? "Gemini Web調査・AI抽出"
                              : "simulator・架空データ"}{" "}
                            /{" "}
                            {s.mode === "live"
                              ? date(s.retrieved_at)
                              : s.retrieved_at}
                            {s.source_url && (
                              <>
                                <br />
                                <a
                                  href={s.source_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  出典ページ
                                </a>
                              </>
                            )}
                            {s.evidence && (
                              <>
                                <br />
                                抽出根拠：{s.evidence}
                              </>
                            )}
                          </p>
                        ))}
                      </details>
                    </div>
                  ))}
                  <p className="whitespace-pre-wrap">{detail.notes}</p>
                  <div className="history-prices">
                    <span>工賃 {yen(detail.labor_total)}</span>
                    <span>部品 {yen(detail.parts_total)}</span>
                    <span>税 {yen(detail.tax_amount)}</span>
                  </div>
                  <p className="detail-total">
                    税込合計 <strong>{yen(detail.total_amount)}</strong>
                  </p>
                  <p className="note">
                    保存時の金額・条件です。再利用するときは適合と価格を再確認してください。
                  </p>
                  <button
                    className="primary-button"
                    onClick={() => reuse(detail)}
                  >
                    この条件で見積もりを作る
                  </button>
                </div>
              </>
            ) : (
              <>
                <label className="search-input history-search">
                  <Icon name="search" />
                  <input
                    aria-label="見積もり履歴を検索"
                    value={historyQuery}
                    onChange={(e) => setHistoryQuery(e.target.value)}
                    placeholder="車種・型式・年式・作業で検索"
                  />
                </label>
                <p className="muted">
                  {history.length}件の見積もり / 保存日時は日本時間
                </p>
                <div className="history-list">
                  {history.length ? (
                    history.map((h) => (
                      <button
                        key={h.id}
                        onClick={() => {
                          setBusy(true);
                          api<Saved>("/estimates/" + h.id)
                            .then(setDetail)
                            .catch((e) => setError(e.message))
                            .finally(() => setBusy(false));
                        }}
                        disabled={busy}
                      >
                        <div>
                          <strong>
                            {h.vehicle.model}{" "}
                            <span>{h.vehicle.model_code}</span>
                          </strong>
                          <p>
                            {h.year}年 / {h.items.map((i) => i.name).join("、")}
                          </p>
                          <small>{date(h.created_at)}</small>
                        </div>
                        <b>{yen(h.total_amount)}</b>
                        <Icon name="chevron" />
                      </button>
                    ))
                  ) : (
                    <div className="empty">
                      <Icon name="save" size={32} />
                      <p>
                        保存した見積もりがありません。
                        <br />
                        金額を確定して保存すると、ここに表示されます。
                      </p>
                    </div>
                  )}
                </div>
              </>
            )}
          </dialog>
        </div>
      )}
      <div hidden={view !== "profit"}>
        <ProfitDashboard />
      </div>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
