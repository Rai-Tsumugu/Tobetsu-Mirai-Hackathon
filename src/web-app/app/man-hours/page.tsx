import type { Metadata } from "next";
import Link from "next/link";
import exampleCase from "../../../30-algorithm/integrated/data/case_example.json";
import ManHoursApp from "./ManHoursApp";
import "./man-hours.css";

export const metadata: Metadata = { title: "工数見積もり | 当別未来フェス" };

export default function ManHoursPage() {
  return (
    <main className="sys-man-hours">
      <header className="mh-top">
        <Link className="mh-back" href="/">
          ← トップへ戻る
        </Link>
        <h1>工数見積もり（決定版）</h1>
        <p className="mh-lead">
          基準工数と入庫時の観察から、人時を low / typical / high の3点で示します。計算は提案で、確定は整備士・見積もり担当者が行います。
          数値はすべて架空の暫定値です。
        </p>
      </header>
      <ManHoursApp initialCase={JSON.stringify(exampleCase, null, 2)} />
    </main>
  );
}
