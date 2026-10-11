// store.py の QuoteStore 契約。本番は Neon（lib/db/repositories/quote-store.ts）、
// テストは SQLite と同じ振る舞いをするメモリ実装（MemoryQuoteStore）を使う。
import { demo_presets } from "./fixtures";
import { deepcopy, get, IntegrityErr, isInt, item, KeyErr, numStr, pyEq, TypeErr, ValueErr, type Obj } from "./pyrt";

export interface QuoteStore {
  /** 入れ子にできるトランザクション。例外が出たら外側ごと取り消す。 */
  transaction<T>(fn: () => Promise<T>): Promise<T>;
  save_quote(quote: unknown): Promise<Obj>;
  get_quote(quote_id: unknown, quote_version?: unknown): Promise<Obj>;
  list_quotes(customer_ref?: unknown, vehicle_ref?: unknown, job_ref?: unknown): Promise<Obj[]>;
  append_communication(record: unknown): Promise<Obj>;
  list_communications(quote_id: unknown): Promise<Obj[]>;
  append_change_event(event: unknown): Promise<Obj>;
  list_change_events(quote_id: unknown): Promise<Obj[]>;
  save_draft(draft: unknown): Promise<Obj>;
  get_draft(draft_id: unknown): Promise<Obj>;
  list_drafts(): Promise<Obj[]>;
  save_price(entry: unknown): Promise<void>;
  list_prices(item_id: unknown): Promise<Obj[]>;
  /** 承認済みの作業プリセット（元は fixtures.demo_presets()）。 */
  list_presets(): Promise<Obj[]>;
}

/** store.save_quote と同じ入力検査。 */
export function checkQuoteIdentity(quote: Obj): { quoteId: string; quoteVersion: number } {
  const quoteId = get(quote, "quote_id");
  const quoteVersion = get(quote, "quote_version");
  if (typeof quoteId !== "string" || !quoteId.trim()) throw new ValueErr("quote_id is required");
  if (!isInt(quoteVersion) || quoteVersion < 1) throw new ValueErr("quote_version must be positive integer");
  return { quoteId, quoteVersion };
}

/** json.dumps(value, allow_nan=False) */
export function encodeJson(value: unknown): string {
  const check = (entry: unknown): void => {
    if (typeof entry === "number" && !Number.isFinite(entry)) {
      throw new ValueErr(`Out of range float values are not JSON compliant: ${Number.isNaN(entry) ? "nan" : entry > 0 ? "inf" : "-inf"}`);
    }
    if (Array.isArray(entry)) entry.forEach(check);
    else if (entry !== null && typeof entry === "object") Object.values(entry).forEach(check);
  };
  check(value);
  return JSON.stringify(value);
}

/** SQLite の TEXT 列に入る値（数値は文字列になる）。 */
function textAffinity(value: unknown): unknown {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "1" : "0";
  if (typeof value === "number") return numStr(value);
  throw new TypeErr(`Error binding parameter: type '${Array.isArray(value) ? "list" : "dict"}' is not supported`);
}

type QuoteRow = { quote_id: unknown; quote_version: unknown; customer_ref: unknown; vehicle_ref: unknown; job_ref: unknown; snapshot: string };
type EventRow = { id: unknown; quote_id: unknown; quote_version: unknown; snapshot: string };
type DraftRow = { draft_id: unknown; snapshot: string };
type PriceRow = { history_id: number; item_id: unknown; snapshot: string };
type State = { quotes: QuoteRow[]; communications: EventRow[]; changes: EventRow[]; drafts: DraftRow[]; prices: PriceRow[] };

/** SQLite 版 QuoteStore と同じ制約（主キー・外部キー・NOT NULL）を持つメモリ実装。 */
export class MemoryQuoteStore implements QuoteStore {
  private state: State = { quotes: [], communications: [], changes: [], drafts: [], prices: [] };
  private depth = 0;

  constructor(private readonly presets: Obj[] = demo_presets()) {}

  async transaction<T>(fn: () => Promise<T>): Promise<T> {
    const outermost = this.depth === 0;
    const saved = outermost ? deepcopy(this.state) : null;
    this.depth += 1;
    try {
      return await fn();
    } catch (error) {
      if (outermost && saved) this.state = saved;
      throw error;
    } finally {
      this.depth -= 1;
    }
  }

  async save_quote(quote: unknown): Promise<Obj> {
    const copy = deepcopy(quote) as Obj;
    const { quoteId, quoteVersion } = checkQuoteIdentity(copy);
    return this.transaction(async () => {
      const row: QuoteRow = {
        quote_id: quoteId,
        quote_version: quoteVersion,
        customer_ref: textAffinity(get(copy, "customer_ref")),
        vehicle_ref: textAffinity(get(copy, "vehicle_ref")),
        job_ref: textAffinity(get(copy, "job_ref")),
        snapshot: encodeJson(copy),
      };
      if (this.state.quotes.some((entry) => entry.quote_id === quoteId && entry.quote_version === quoteVersion)) {
        throw new IntegrityErr("UNIQUE constraint failed: quote_versions.quote_id, quote_versions.quote_version");
      }
      this.state.quotes.push(row);
      return copy;
    });
  }

  async get_quote(quote_id: unknown, quote_version: unknown = null): Promise<Obj> {
    const rows = this.state.quotes.filter((entry) => sqlEq(entry.quote_id, quote_id));
    let row: QuoteRow | undefined;
    if (quote_version === null || quote_version === undefined) {
      row = [...rows].sort((a, b) => Number(b.quote_version) - Number(a.quote_version))[0];
    } else {
      row = rows.find((entry) => sqlEq(entry.quote_version, quote_version));
    }
    if (!row) throw new ValueErr("quote version not found");
    return JSON.parse(row.snapshot);
  }

  async list_quotes(customer_ref: unknown = null, vehicle_ref: unknown = null, job_ref: unknown = null): Promise<Obj[]> {
    const rows = this.state.quotes.filter(
      (entry) =>
        (customer_ref === null || sqlEq(entry.customer_ref, customer_ref)) &&
        (vehicle_ref === null || sqlEq(entry.vehicle_ref, vehicle_ref)) &&
        (job_ref === null || sqlEq(entry.job_ref, job_ref)),
    );
    const sorted = [...rows].sort(
      (a, b) => Number(b.quote_version) - Number(a.quote_version) || compareBinary(String(a.quote_id), String(b.quote_id)),
    );
    return sorted.map((entry) => JSON.parse(entry.snapshot));
  }

  private appendEvent(table: "communications" | "changes", id: unknown, quoteId: unknown, quoteVersion: unknown, record: Obj): void {
    const name = table === "communications" ? "communications" : "change_events";
    const idName = table === "communications" ? "communication_id" : "event_id";
    if (quoteId === null) throw new IntegrityErr(`NOT NULL constraint failed: ${name}.quote_id`);
    if (quoteVersion === null) throw new IntegrityErr(`NOT NULL constraint failed: ${name}.quote_version`);
    const snapshot = encodeJson(record);
    const key = textAffinity(id);
    if (key !== null && this.state[table].some((entry) => entry.id === key)) {
      throw new IntegrityErr(`UNIQUE constraint failed: ${name}.${idName}`);
    }
    if (!this.state.quotes.some((entry) => sqlEq(entry.quote_id, quoteId) && sqlEq(entry.quote_version, quoteVersion))) {
      throw new IntegrityErr("FOREIGN KEY constraint failed");
    }
    this.state[table].push({ id: key, quote_id: textAffinity(quoteId), quote_version: quoteVersion, snapshot });
  }

  async append_communication(record: unknown): Promise<Obj> {
    const values = [item(record, "communication_id"), item(record, "quote_id"), item(record, "quote_version")];
    await this.transaction(async () => this.appendEvent("communications", values[0], values[1], values[2], record as Obj));
    return deepcopy(record as Obj);
  }

  async list_communications(quote_id: unknown): Promise<Obj[]> {
    return this.state.communications.filter((entry) => sqlEq(entry.quote_id, quote_id)).map((entry) => JSON.parse(entry.snapshot));
  }

  async append_change_event(event: unknown): Promise<Obj> {
    const values = [item(event, "event_id"), item(event, "quote_id"), item(event, "to_version")];
    await this.transaction(async () => this.appendEvent("changes", values[0], values[1], values[2], event as Obj));
    return deepcopy(event as Obj);
  }

  async list_change_events(quote_id: unknown): Promise<Obj[]> {
    return this.state.changes.filter((entry) => sqlEq(entry.quote_id, quote_id)).map((entry) => JSON.parse(entry.snapshot));
  }

  async save_draft(draft: unknown): Promise<Obj> {
    const draftId = textAffinity(item(draft, "draft_id"));
    const snapshot = encodeJson(draft);
    await this.transaction(async () => {
      const existing = draftId === null ? undefined : this.state.drafts.find((entry) => entry.draft_id === draftId);
      if (existing) existing.snapshot = snapshot;
      else this.state.drafts.push({ draft_id: draftId, snapshot });
    });
    return deepcopy(draft as Obj);
  }

  async get_draft(draft_id: unknown): Promise<Obj> {
    const row = this.state.drafts.find((entry) => sqlEq(entry.draft_id, draft_id));
    if (!row) throw new ValueErr("draft not found");
    return JSON.parse(row.snapshot);
  }

  async list_drafts(): Promise<Obj[]> {
    return [...this.state.drafts].reverse().map((entry) => JSON.parse(entry.snapshot));
  }

  async save_price(entry: unknown): Promise<void> {
    const itemId = item(entry, "item_id");
    const snapshot = encodeJson(entry);
    await this.transaction(async () => {
      if (itemId === null) throw new IntegrityErr("NOT NULL constraint failed: price_history.item_id");
      const historyId = this.state.prices.reduce((max, row) => Math.max(max, row.history_id), 0) + 1;
      this.state.prices.push({ history_id: historyId, item_id: textAffinity(itemId), snapshot });
    });
  }

  async list_prices(item_id: unknown): Promise<Obj[]> {
    return this.state.prices.filter((entry) => sqlEq(entry.item_id, item_id)).map((entry) => JSON.parse(entry.snapshot));
  }

  async list_presets(): Promise<Obj[]> {
    return deepcopy(this.presets);
  }

  /** ゴールデンの記録と同じ形の状態（テスト用）。 */
  dump(): Obj {
    return {
      quote_versions: this.state.quotes.map((r) => [r.quote_id, r.quote_version, r.customer_ref, r.vehicle_ref, r.job_ref, JSON.parse(r.snapshot)]),
      communications: this.state.communications.map((r) => [r.id, r.quote_id, r.quote_version, JSON.parse(r.snapshot)]),
      change_events: this.state.changes.map((r) => [r.id, r.quote_id, r.quote_version, JSON.parse(r.snapshot)]),
      drafts: this.state.drafts.map((r) => [r.draft_id, JSON.parse(r.snapshot)]),
      price_history: this.state.prices.map((r) => [r.history_id, r.item_id, JSON.parse(r.snapshot)]),
    };
  }

  /** dump() の形から状態を読み込む（テスト用）。 */
  load(state: Obj): this {
    this.state = {
      quotes: state.quote_versions.map((r: unknown[]) => ({
        quote_id: r[0], quote_version: r[1], customer_ref: r[2], vehicle_ref: r[3], job_ref: r[4], snapshot: JSON.stringify(r[5]),
      })),
      communications: state.communications.map((r: unknown[]) => ({ id: r[0], quote_id: r[1], quote_version: r[2], snapshot: JSON.stringify(r[3]) })),
      changes: state.change_events.map((r: unknown[]) => ({ id: r[0], quote_id: r[1], quote_version: r[2], snapshot: JSON.stringify(r[3]) })),
      drafts: state.drafts.map((r: unknown[]) => ({ draft_id: r[0], snapshot: JSON.stringify(r[1]) })),
      prices: state.price_history.map((r: unknown[]) => ({ history_id: r[0] as number, item_id: r[1], snapshot: JSON.stringify(r[2]) })),
    };
    return this;
  }
}

/** SQLite の = （TEXT 列は数値の引数も文字列として比べる）。 */
function sqlEq(column: unknown, value: unknown): boolean {
  if (column === null || value === null || value === undefined) return false;
  if (typeof column === "string" && typeof value === "number") return column === numStr(value);
  return pyEq(column, value) && typeof column === typeof value;
}

function compareBinary(a: string, b: string): number {
  const left = Buffer.from(a, "utf8");
  const right = Buffer.from(b, "utf8");
  return Buffer.compare(left, right);
}

export { KeyErr };
