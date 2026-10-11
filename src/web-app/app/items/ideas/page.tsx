import type { Metadata } from "next";
import IdeasClient from "./ideas-client";
import "../items.css";

export const metadata: Metadata = {
  title: "材料台帳 · 30の道具 | 部品・材料単価",
};

export default function ItemsIdeasPage() {
  return <IdeasClient />;
}
