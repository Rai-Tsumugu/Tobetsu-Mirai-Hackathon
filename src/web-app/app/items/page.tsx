import type { Metadata } from "next";
import WorkspaceClient from "./workspace-client";
import "./items.css";

export const metadata: Metadata = {
  title: "材料・見積ワークスペース | 部品・材料単価",
};

export default function ItemsWorkspacePage() {
  return <WorkspaceClient />;
}
