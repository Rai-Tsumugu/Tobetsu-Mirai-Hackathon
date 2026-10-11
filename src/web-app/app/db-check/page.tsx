import { getDatabase } from "@/lib/db";

export const dynamic = "force-dynamic";

type DisplaySample = {
  label: string;
  value: number;
  unit: string;
};

export default async function DatabaseCheckPage() {
  let sample: DisplaySample | undefined = {
    label: "画面確認用サンプル",
    value: 1234,
    unit: "件",
  };
  let state: "sample" | "unavailable" | "empty" | "connected" = "sample";

  if (process.env.DATABASE_URL) {
    sample = undefined;
    try {
      const sql = getDatabase();
      const rows = await sql`
        SELECT label, value, unit
        FROM db_display_check
        WHERE id = 1
      `;
      sample = rows[0] as DisplaySample | undefined;
      state = sample ? "connected" : "empty";
    } catch {
      state = "unavailable";
    }
  }

  return (
    <main className="page-shell db-check-page">
      <header className="topbar">
        <a className="brand" href="/">
          <span className="brand-mark">T</span>
          <span>TOBETSU <span className="brand-light">/ DATABASE CHECK</span></span>
        </a>
        <a className="db-back-link" href="/">トップへ戻る</a>
      </header>

      <section className="db-check-content">
        <p className="eyebrow">NEON POSTGRESQL · READ CHECK</p>
        <h1>数値表示の確認</h1>
        <p className="db-check-intro">
          Neon接続前はサンプル値を、接続後はテーブルから読み込んだ数値を表示します。
        </p>

        {(state === "connected" || state === "sample") && sample && (
          <article className={`db-metric-card ${state === "sample" ? "is-sample" : ""}`}>
            <span className="db-metric-label">{sample.label}</span>
            <p className="db-metric-value">
              {new Intl.NumberFormat("ja-JP").format(sample.value)}
              <span>{sample.unit}</span>
            </p>
            <span className="db-connection-state">
              {state === "sample" ? "SAMPLE · DATABASE NOT CONNECTED" : "DATABASE CONNECTED"}
            </span>
          </article>
        )}

        {state === "unavailable" && (
          <p className="db-message" role="status">
            DBに接続できないか、確認用テーブルがありません。`db/display-check.sql` をNeon SQL Editorで実行してください。
          </p>
        )}
        {state === "empty" && (
          <p className="db-message" role="status">
            確認用テーブルにデータがありません。`db/display-check.sql` をNeon SQL Editorで実行してください。
          </p>
        )}
      </section>
    </main>
  );
}
