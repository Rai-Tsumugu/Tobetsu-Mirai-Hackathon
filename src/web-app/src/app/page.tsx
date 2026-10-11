const setupItems = [
  { number: "01", title: "テーマを選ぶ", detail: "A・B・Cから取り組む課題を決めます。" },
  { number: "02", title: "MVPを決める", detail: "入力・処理・結果と、実演の条件を整理します。" },
  { number: "03", title: "アプリを作る", detail: "この場所に画面と処理を実装していきます。" },
];

export default function Home() {
  return (
    <main className="page-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="当別未来フェス ハッカソン">
          <span className="brand-mark">T</span>
          <span>TOBETSU <span className="brand-light">/ HACKATHON</span></span>
        </a>
        <span className="status"><span className="status-dot" />開発環境を準備しました</span>
      </header>

      <section className="hero" id="top">
        <p className="eyebrow">TOBETSU MIRAI FES · WEB APP</p>
        <h1>アイデアを、<br /><span>動くかたちに。</span></h1>
        <p className="intro">
          当別の事業者が抱える課題に向き合う、チームのWebアプリです。
          テーマとMVPが決まったら、このプロジェクトに機能を実装していきます。
        </p>
        <div className="hero-note"><span className="note-icon">↳</span> 現在はアプリの土台を準備した状態です</div>
      </section>

      <section className="next-steps" aria-labelledby="steps-heading">
        <div className="section-heading">
          <p className="eyebrow">GETTING STARTED</p>
          <h2 id="steps-heading">ここから始める</h2>
        </div>
        <div className="step-grid">
          {setupItems.map((item) => (
            <article className="step-card" key={item.number}>
              <span className="step-number">{item.number}</span>
              <h3>{item.title}</h3>
              <p>{item.detail}</p>
              <span className="step-arrow" aria-hidden="true">↗</span>
            </article>
          ))}
        </div>
      </section>

      <footer className="footer">
        <span>TOBETSU MIRAI FES</span>
        <span>Built for ideas that move the town forward.</span>
      </footer>
    </main>
  );
}
