// GET /api/items/prices: 保存済みの価格版の台帳（元の GET /api/prices）。
import { withTransaction } from "@/lib/db";
import { sendJson } from "@/lib/systems/items/http";
import { PgStore } from "@/lib/systems/items/pg-store";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const priceVersions = await withTransaction((tx) => new PgStore(tx).priceVersions());
    return sendJson(200, { mode: "simulator", price_versions: priceVersions });
  } catch (error) {
    console.error("items prices error", error);
    return sendJson(500, { error: "台帳の読込に失敗しました" });
  }
}
