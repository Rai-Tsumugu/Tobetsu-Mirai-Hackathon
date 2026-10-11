// golden/generate.py の Normalizer と同じ規則。時刻を <TS>、ランダムな ID を初出順の <ID:n> に置き換える。
const TS = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00$/;
const ID = /^(CASE-[0-9a-f]{32}|manual-[0-9a-f]{12}|live-[0-9a-f]{16}|[0-9a-f]{12}|[0-9a-f]{32})$/;

export class Normalizer {
  private readonly ids = new Map<string, string>();

  value(value: unknown): unknown {
    if (Array.isArray(value)) return value.map((v) => this.value(v));
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, this.value(v)]));
    }
    if (typeof value === "string") {
      if (TS.test(value)) return "<TS>";
      if (ID.test(value)) {
        if (!this.ids.has(value)) this.ids.set(value, `<ID:${this.ids.size}>`);
        return this.ids.get(value);
      }
    }
    return value;
  }

  /** 422 の検証エラーは type・loc・msg だけを比べる（Pydantic の url・ctx・input は持たない）。 */
  response(status: number, body: unknown): unknown {
    if (status === 422 && body && typeof body === "object" && Array.isArray((body as { detail?: unknown }).detail)) {
      const detail = (body as { detail: { type: string; loc: unknown[]; msg: string }[] }).detail;
      body = { detail: detail.map((e) => ({ type: e.type, loc: e.loc, msg: e.msg })) };
    }
    return this.value(body);
  }
}

/** オブジェクトのキーの順序まで比べるため、JSON 文字列にして比べる。 */
export function ordered(value: unknown): string {
  return JSON.stringify(value, null, 1);
}
