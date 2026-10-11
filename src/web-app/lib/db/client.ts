import { neon, Pool } from "@neondatabase/serverless";
import { transaction, type Database, type Transaction } from "./queryable";

function connectionString(): string {
  const value = process.env.DATABASE_URL;
  if (!value) {
    throw new Error("DATABASE_URL is not configured");
  }
  return value;
}

/** 単発のクエリ用（HTTP）。タグ付きテンプレートで使う。 */
export function getDatabase() {
  return neon(connectionString());
}

/**
 * リポジトリ用の接続を1リクエストの間だけ開く。
 * サーバーレスでは接続をリクエストをまたいで持ち越さないため、処理の後に必ず閉じる。
 */
export async function withDatabase<T>(fn: (db: Database) => Promise<T>): Promise<T> {
  const pool = new Pool({ connectionString: connectionString() });
  try {
    return await fn(pool);
  } finally {
    await pool.end();
  }
}

export function withTransaction<T>(fn: (tx: Transaction) => Promise<T>): Promise<T> {
  return withDatabase((db) => transaction(db, fn));
}
