// ドライバーに依存しない最小の接続インターフェース。
// 本番は @neondatabase/serverless の Pool、スクリプトとテストは pg の Pool を渡す（どちらも pg 互換）。

export type QueryResult = { rows: unknown[]; rowCount?: number | null };

export interface Queryable {
  query(text: string, values?: unknown[]): Promise<QueryResult>;
}

export interface PoolClientLike extends Queryable {
  release(error?: Error | boolean): void;
}

export interface PoolLike extends Queryable {
  connect(): Promise<PoolClientLike>;
}

/** BEGIN〜COMMIT の間だけ有効な接続。入れ子の transaction() はセーブポイントになる。 */
export class Transaction implements Queryable {
  private savepointDepth = 0;

  constructor(private readonly client: PoolClientLike) {}

  query(text: string, values?: unknown[]): Promise<QueryResult> {
    return this.client.query(text, values);
  }

  async savepoint<T>(fn: (tx: Transaction) => Promise<T>): Promise<T> {
    const name = `sp_${++this.savepointDepth}`;
    await this.client.query(`SAVEPOINT ${name}`);
    try {
      const result = await fn(this);
      await this.client.query(`RELEASE SAVEPOINT ${name}`);
      return result;
    } catch (error) {
      await this.client.query(`ROLLBACK TO SAVEPOINT ${name}`);
      await this.client.query(`RELEASE SAVEPOINT ${name}`);
      throw error;
    } finally {
      this.savepointDepth -= 1;
    }
  }
}

/** リポジトリが受け取る接続。プールか、実行中のトランザクション。 */
export type Database = PoolLike | Transaction;

export async function transaction<T>(db: Database, fn: (tx: Transaction) => Promise<T>): Promise<T> {
  if (db instanceof Transaction) {
    return db.savepoint(fn);
  }
  const client = await db.connect();
  const tx = new Transaction(client);
  try {
    await client.query("BEGIN");
    const result = await fn(tx);
    await client.query("COMMIT");
    return result;
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

export async function queryRows<T>(db: Queryable, text: string, values?: unknown[]): Promise<T[]> {
  const result = await db.query(text, values);
  return result.rows as T[];
}

export async function queryOne<T>(db: Queryable, text: string, values?: unknown[]): Promise<T | undefined> {
  const rows = await queryRows<T>(db, text, values);
  return rows[0];
}
