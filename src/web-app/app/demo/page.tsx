// 整備見積ワークベンチ（元: src/app-demo）。案件一覧・見積もり作成・保存した見積もり・売上利益のモック・帳票PDF。
import type { Metadata, Viewport } from "next";
import DemoClient from "./DemoClient";

export const metadata: Metadata = {
  title: "整備見積ワークベンチ | 当別デモ",
};

export const viewport: Viewport = {
  themeColor: "#163b68",
};

export default function DemoPage() {
  return (
    <div className="sys-demo">
      <DemoClient />
    </div>
  );
}
