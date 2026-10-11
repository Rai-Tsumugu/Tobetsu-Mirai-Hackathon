// 部品・材料単価の架空の初期データ。元の app.py が起動時に呼ぶ seed_demo と同じ
// （架空サンプル塗料 demo-paint: 仕入80円・販売120円 / ml）。何度実行しても同じ状態になる。
import type { Transaction } from "../../db/queryable";
import { seedDemo } from "./core";
import { PgStore } from "./pg-store";

export async function seedItems(db: Transaction): Promise<void> {
  // lib/db/seed.ts が同じ品目を登録済みなら何もしない（seed_demo と同じ判定）。
  await seedDemo(new PgStore(db));
}
