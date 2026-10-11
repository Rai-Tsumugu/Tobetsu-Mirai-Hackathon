import { getDatabase } from "@/lib/db";

export const dynamic = "force-dynamic";

type DisplaySample = {
  label: string;
  value: number;
  unit: string;
};

export default async function DatabaseCheckPage() {
  let sample: DisplaySample | undefined;
  let state: "not-configured" | "unavailable" | "empty" | "connected" = "not-configured";

  if (process.env.DATABASE_URL) {
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
          Neonのテーブルから読み込んだ数値を表示します。
        </p>

        {state === "connected" && sample && (
          <article className="db-metric-card">
            <span className="db-metric-label">{sample.label}</span>
            <p className="db-metric-value">
              {new Intl.NumberFormat("ja-JP").format(sample.value)}
              <span>{sample.unit}</span>
            </p>
            <span className="db-connection-state">DATABASE CONNECTED</span>
          </article>
        )}

        {state === "not-configured" && (
          <p className="db-message" role="status">
            DATABASE_URLが未設定です。Neonの接続文字列を `.env.local` に設定してください。
          </p>
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
