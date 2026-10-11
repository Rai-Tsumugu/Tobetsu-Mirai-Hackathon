import Link from "next/link";

const systems = [
  {
    number: "01",
    href: "/demo",
    title: "整備見積ワークベンチ",
    detail: "案件の登録から、参考工賃の比較、見積もりの保存、見積書・請求書のPDFまでを通して操作します。",
  },
  {
    number: "02",
    href: "/quote",
    title: "整備見積 統合版",
    detail: "工賃と品目を3つの帯で積算し、担当者が帯と確定額を選んで、顧客への説明と版の履歴を残します。",
  },
  {
    number: "03",
    href: "/man-hours",
    title: "工数見積もり",
    detail: "車両の状態と過去の実績から、作業の人時を少ない・標準・多いの3点で見積もります。",
  },
  {
    number: "04",
    href: "/engine",
    title: "工数エンジン 30案",
    detail: "工数計算エンジンの30の方式と統合版を、同じ入力で計算して比べます。",
  },
  {
    number: "05",
    href: "/items",
    title: "部品・材料単価マスタ",
    detail: "部品・材料の単価を登録・取込・承認し、見積もりと実使用量へつなぎます。",
  },
];

export default function Home() {
  return (
    <main className="page-shell">
      <header className="topbar">
        <Link className="brand" href="/" aria-label="当別未来フェス ハッカソン">
          <span className="brand-mark">T</span>
          <span>TOBETSU <span className="brand-light">/ HACKATHON</span></span>
        </Link>
        <span className="status"><span className="status-dot" />5つのシステムを公開中</span>
      </header>

      <section className="hero" id="top">
        <p className="eyebrow">TOBETSU MIRAI FES · WEB APP</p>
        <h1>整備の見積もりを、<br /><span>根拠から組み立てる。</span></h1>
        <p className="intro">
          当別の自動車整備工場の見積もり業務を支えるシステム群です。工数・単価・見積もりの各システムを、ここから開けます。
        </p>
        <div className="hero-note"><span className="note-icon">↳</span> 価格・人時などの値はすべて架空のデモデータです</div>
      </section>

      <section className="next-steps" aria-labelledby="systems-heading">
        <div className="section-heading">
          <p className="eyebrow">SYSTEMS</p>
          <h2 id="systems-heading">システム一覧</h2>
        </div>
        <div className="step-grid">
          {systems.map((system) => (
            <Link className="step-card" href={system.href} key={system.href}>
              <span className="step-number">{system.number}</span>
              <h3>{system.title}</h3>
              <p>{system.detail}</p>
              <span className="step-arrow" aria-hidden="true">↗</span>
            </Link>
          ))}
        </div>
      </section>

      <footer className="footer">
        <span>TOBETSU MIRAI FES</span>
        <Link href="/db-check">DB接続の確認</Link>
      </footer>
    </main>
  );
}
