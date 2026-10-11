"use client";
// 元: src/app-demo/frontend/src/ProfitDashboard.tsx（変更なし）。
import { useState } from "react";
import "./profit.css";

const asYen = (value: number) => `¥${value.toLocaleString("ja-JP")}`;
const snapshot = "2026-10-11";
const opening = "2023-01-01";
const dayMs = 86400000;
const categories = [
  { name: "オイル交換", price: 6800, parts: 3100, labor: 1200, overhead: 500 },
  {
    name: "ブレーキ整備",
    price: 24800,
    parts: 12500,
    labor: 4200,
    overhead: 1500,
  },
  {
    name: "バッテリー交換",
    price: 28600,
    parts: 17800,
    labor: 2200,
    overhead: 900,
  },
  {
    name: "点検・消耗品",
    price: 8800,
    parts: 2500,
    labor: 2100,
    overhead: 700,
  },
  {
    name: "外装・その他",
    price: 68000,
    parts: 36500,
    labor: 9500,
    overhead: 3000,
  },
];
const periods = [
  { id: "day", name: "1日", start: snapshot, caption: "今日の収支" },
  { id: "week", name: "1週間", start: "2026-10-05", caption: "今週の収支" },
  { id: "month", name: "1ヶ月", start: "2026-10-01", caption: "今月の収支" },
  { id: "year", name: "1年", start: "2026-01-01", caption: "今年の収支" },
  { id: "lifetime", name: "生涯", start: opening, caption: "開業からの累計" },
];
// One deterministic fictional ledger. Every period is a slice of the same data.
const ledger = Array.from(
  { length: (Date.parse(snapshot) - Date.parse(opening)) / dayMs + 1 },
  (_, day) => {
    const date = new Date(Date.parse(opening) + day * dayMs)
      .toISOString()
      .slice(0, 10);
    return categories.map((category, index) => {
      const count =
        index === 0 ? 3 + (day % 5) : 1 + ((day * 7 + index * 3) % 3);
      return {
        date,
        index,
        count,
        sales: count * category.price,
        parts: count * category.parts,
        labor: count * category.labor,
        overhead: count * category.overhead,
      };
    });
  },
).flat();
const dateLabel = (date: string) => date.replaceAll("-", "/");

export default function ProfitDashboard() {
  const [periodId, setPeriodId] = useState("month");
  const period = periods.find((p) => p.id === periodId)!;
  const entries = ledger.filter(
    (e) => e.date >= period.start && e.date <= snapshot,
  );
  const rows = categories.map((category, index) => {
    const total = entries
      .filter((e) => e.index === index)
      .reduce(
        (sum, entry) => ({
          count: sum.count + entry.count,
          sales: sum.sales + entry.sales,
          parts: sum.parts + entry.parts,
          labor: sum.labor + entry.labor,
          overhead: sum.overhead + entry.overhead,
        }),
        { count: 0, sales: 0, parts: 0, labor: 0, overhead: 0 },
      );
    const cost = total.parts + total.labor + total.overhead;
    return { ...total, name: category.name, cost, profit: total.sales - cost };
  });
  const totals = rows.reduce(
    (sum, row) => ({
      sales: sum.sales + row.sales,
      cost: sum.cost + row.cost,
      profit: sum.profit + row.profit,
      count: sum.count + row.count,
      parts: sum.parts + row.parts,
      labor: sum.labor + row.labor,
      overhead: sum.overhead + row.overhead,
    }),
    { sales: 0, cost: 0, profit: 0, count: 0, parts: 0, labor: 0, overhead: 0 },
  );
  const margin = (totals.profit / totals.sales) * 100;
  const costShare = 100 - margin;
  const radius = 105;
  const circumference = 2 * Math.PI * radius;
  const costItems = [
    { name: "部品・材料費", value: totals.parts },
    { name: "人件費", value: totals.labor },
    { name: "運営費", value: totals.overhead },
  ];
  return (
    <main className="profit-page">
      <div className="profit-heading">
        <div>
          <p className="profit-location">整備工場の収支</p>
          <h1>働いた成果を、ひと目で。</h1>
          <p className="profit-description">
            売上からコストを引いて、手元に残る利益を確認。
          </p>
        </div>
        <span className="profit-mock-badge">架空データ / モックアップ</span>
      </div>
      <div className="profit-period-bar">
        <nav aria-label="集計期間" className="profit-periods">
          {periods.map((p) => (
            <button
              key={p.id}
              aria-pressed={periodId === p.id}
              onClick={() => setPeriodId(p.id)}
            >
              {p.name}
            </button>
          ))}
        </nav>
        <p>
          {dateLabel(period.start)} — {dateLabel(snapshot)}
        </p>
      </div>
      <section
        className="profit-overview"
        aria-labelledby="profit-overview-title"
        aria-live="polite"
      >
        <div className="profit-ring-section">
          <div className="profit-section-heading">
            <h2 id="profit-overview-title">{period.caption}</h2>
            <span>すべて税抜</span>
          </div>
          <div className="profit-ring-wrap">
            <svg
              viewBox="0 0 260 260"
              role="img"
              aria-label={`売上 ${asYen(totals.sales)}のうち、コスト ${costShare.toFixed(1)}%、利益 ${margin.toFixed(1)}%`}
            >
              <circle
                cx="130"
                cy="130"
                r={radius}
                fill="none"
                stroke="#f0b26c"
                strokeWidth="15"
              />
              <circle
                cx="130"
                cy="130"
                r={radius}
                fill="none"
                stroke="#248f85"
                strokeWidth="15"
                strokeDasharray={`${(circumference * margin) / 100} ${circumference}`}
                transform="rotate(-90 130 130)"
                strokeLinecap="round"
              />
            </svg>
            <div className="profit-ring-center">
              <span>利益</span>
              <strong
                className={totals.profit >= 100000000 ? "large-amount" : ""}
                data-testid="profit-total"
              >
                {asYen(totals.profit)}
              </strong>
              <small>
                利益率 <b>{margin.toFixed(1)}%</b>
              </small>
            </div>
          </div>
          <div className="profit-legend">
            <span>
              <i className="profit-dot" />
              利益 {margin.toFixed(1)}%
            </span>
            <span>
              <i className="cost-dot" />
              コスト {costShare.toFixed(1)}%
            </span>
          </div>
        </div>
        <div className="profit-numbers">
          <div className="profit-sale-line">
            <div>
              <span>売上</span>
              <p>整備・交換で得た収入</p>
            </div>
            <strong data-testid="sales-total">{asYen(totals.sales)}</strong>
          </div>
          <div className="profit-cost-line">
            <div>
              <span>コスト</span>
              <p>部品・人件費・運営費の合計</p>
            </div>
            <strong data-testid="cost-total">−{asYen(totals.cost)}</strong>
          </div>
          <div className="profit-balance-line">
            <span>残った利益</span>
            <strong>{asYen(totals.profit)}</strong>
          </div>
          <div className="profit-work-count">
            <span>期間内の作業数</span>
            <strong>{totals.count.toLocaleString("ja-JP")} 件</strong>
          </div>
          <p className="profit-calculation">
            利益 = 売上 −
            コスト。税金や借入返済などは含まない、モック上の収支です。
          </p>
        </div>
      </section>
      <div className="profit-details-grid">
        <section
          className="profit-table-section"
          aria-labelledby="profit-table-title"
        >
          <div className="profit-section-heading">
            <h2 id="profit-table-title">作業別の売上と利益</h2>
            <span>円 / 税抜</span>
          </div>
          <div className="profit-table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">作業</th>
                  <th scope="col">件数</th>
                  <th scope="col">売上</th>
                  <th scope="col">コスト</th>
                  <th scope="col">利益</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.name}>
                    <th scope="row">{row.name}</th>
                    <td>{row.count.toLocaleString("ja-JP")}</td>
                    <td>{asYen(row.sales)}</td>
                    <td>{asYen(row.cost)}</td>
                    <td className="profit-table-gain">{asYen(row.profit)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">合計</th>
                  <td>{totals.count.toLocaleString("ja-JP")}</td>
                  <td>{asYen(totals.sales)}</td>
                  <td>{asYen(totals.cost)}</td>
                  <td>{asYen(totals.profit)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </section>
        <section
          className="profit-cost-section"
          aria-labelledby="profit-cost-title"
        >
          <div className="profit-section-heading">
            <h2 id="profit-cost-title">コストの内訳</h2>
            <span>計 {asYen(totals.cost)}</span>
          </div>
          {costItems.map((item, i) => (
            <div className="profit-cost-item" key={item.name}>
              <div>
                <span>{item.name}</span>
                <strong>{asYen(item.value)}</strong>
              </div>
              <div className="profit-cost-track">
                <span
                  style={{
                    width: `${(item.value / totals.cost) * 100}%`,
                    background: ["#e8a65e", "#6e93b8", "#a8b9c9"][i],
                  }}
                />
              </div>
              <small>
                コストの {((item.value / totals.cost) * 100).toFixed(1)}%
              </small>
            </div>
          ))}
          <p className="profit-cost-note">
            運営費は家賃・光熱費・設備費などの架空の配賦額です。
          </p>
        </section>
      </div>
      <footer className="profit-footer">
        <span>集計基準日：2026年10月11日 / 開業日：2023年1月1日</span>
        <span>実際の見積もり・売上データとは連動しません</span>
      </footer>
    </main>
  );
}
