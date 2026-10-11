"use client";
// 元はブラウザだけで動く SPA（Vite）。案件一覧の表示方法を localStorage から読むなど、
// サーバーで描画すると初回表示がずれるため、ブラウザでだけ描画する。
import dynamic from "next/dynamic";

const App = dynamic(() => import("./App"), { ssr: false });

export default function DemoClient() {
  return <App />;
}
