// DB の運用コマンド: npm run db:migrate / npm run db:seed
// DATABASE_URL（環境変数、なければ .env.local）の DB に対して実行する。
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";
import { migrate, readMigrations } from "../lib/db/migrate";
import { seedDemoData } from "../lib/db/seed";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MIGRATIONS_DIR = path.join(appRoot, "db/migrations");
const MAN_HOURS_DATA_DIR = path.resolve(appRoot, "../30-algorithm/integrated/data");

async function main(command: string | undefined) {
  if (!process.env.DATABASE_URL) {
    try {
      process.loadEnvFile(path.join(appRoot, ".env.local"));
    } catch {
      // .env.local がなければ環境変数だけを見る
    }
  }
  if (!process.env.DATABASE_URL) {
    throw new Error("DATABASE_URL is not configured");
  }
  const pool = new Pool({ connectionString: process.env.DATABASE_URL });
  try {
    if (command === "migrate") {
      const applied = await migrate(pool, await readMigrations(MIGRATIONS_DIR));
      console.log(applied.length ? `適用しました: ${applied.join(", ")}` : "未適用のマイグレーションはありません");
    } else if (command === "seed") {
      await seedDemoData(pool, MAN_HOURS_DATA_DIR);
      console.log("架空のデモデータを入れました");
    } else {
      throw new Error("使い方: tsx scripts/db.ts migrate | seed");
    }
  } finally {
    await pool.end();
  }
}

main(process.argv[2]).catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
