import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { queryRows, transaction, type PoolLike } from "./queryable";

export type Migration = { version: string; name: string; sql: string };

const FILE_PATTERN = /^(\d{4})_([a-z0-9_]+)\.sql$/;
// 複数の実行が同時に走っても、適用は1つずつ順に行う。
const MIGRATION_LOCK_KEY = "web-app.schema_migrations";

/** db/migrations/NNNN_name.sql を番号順に読む。 */
export async function readMigrations(directory: string): Promise<Migration[]> {
  const files = (await readdir(directory)).filter((file) => file.endsWith(".sql")).sort();
  return Promise.all(
    files.map(async (file) => {
      const match = FILE_PATTERN.exec(file);
      if (!match) {
        throw new Error(`マイグレーションのファイル名が NNNN_name.sql ではありません: ${file}`);
      }
      return { version: match[1], name: match[2], sql: await readFile(path.join(directory, file), "utf8") };
    }),
  );
}

function checksum(sql: string): string {
  return createHash("sha256").update(sql).digest("hex");
}

/**
 * 未適用のマイグレーションを1つのトランザクションで適用し、適用した版を返す。
 * 適用済みのファイルが書き換えられていたら止める（適用済みの内容は新しい版で直す）。
 */
export async function migrate(db: PoolLike, migrations: Migration[]): Promise<string[]> {
  return transaction(db, async (tx) => {
    await tx.query("SELECT pg_advisory_xact_lock(hashtext($1))", [MIGRATION_LOCK_KEY]);
    await tx.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version    text PRIMARY KEY,
        name       text NOT NULL,
        checksum   text NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now()
      )
    `);
    const applied = new Map(
      (await queryRows<{ version: string; checksum: string }>(tx, "SELECT version, checksum FROM schema_migrations")).map(
        (row) => [row.version, row.checksum],
      ),
    );

    const appliedNow: string[] = [];
    for (const migration of migrations) {
      const sum = checksum(migration.sql);
      const recorded = applied.get(migration.version);
      if (recorded !== undefined) {
        if (recorded !== sum) {
          throw new Error(`適用済みのマイグレーション ${migration.version}_${migration.name} が変更されています`);
        }
        continue;
      }
      await tx.query(migration.sql);
      await tx.query("INSERT INTO schema_migrations (version, name, checksum) VALUES ($1, $2, $3)", [
        migration.version,
        migration.name,
        sum,
      ]);
      appliedNow.push(`${migration.version}_${migration.name}`);
    }
    return appliedNow;
  });
}
