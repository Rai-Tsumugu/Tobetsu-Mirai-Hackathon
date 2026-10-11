// 元の Python（FastAPI / Pydantic / json）と同じ結果にするための小さな道具。

/** FastAPI の HTTPException に当たるエラー。detail は画面にそのまま出す。 */
export class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.name = "HttpError";
  }
}

/**
 * JSON の数値のうち、Python の json.loads で float になるもの（小数点・指数を含む）。
 * 例: 1.0 は JavaScript では 1 と区別できないが、Pydantic の strict な int は拒否する。
 */
export class PyFloat {
  constructor(readonly value: number) {}
}

/** JSON.parse と同じだが、float になる数値を PyFloat で包む。不正な JSON は SyntaxError。 */
export function parsePyJson(text: string): unknown {
  return JSON.parse(text, function (this: unknown, _key: string, value: unknown, context?: { source?: string }) {
    if (typeof value === "number" && context?.source !== undefined && /[.eE]/.test(context.source)) {
      return new PyFloat(value);
    }
    return value;
  } as (this: unknown, key: string, value: unknown) => unknown);
}

/** Python の str.isspace() が真になる文字。 */
const PY_SPACE = "\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, "gu");
/** 正規表現の文字クラスで Python の \s に当たるもの。 */
export const PY_SPACE_CLASS = `[${PY_SPACE}]`;

/** Python の str.strip()。 */
export function pyStrip(value: string): string {
  return value.replace(STRIP, "");
}

/** Python の len(str)（コードポイント数）。 */
export function pyLen(value: string): number {
  let n = 0;
  for (const char of value) {
    void char;
    n += 1;
  }
  return n;
}

/** Python の str[:n]（コードポイント単位で切る）。 */
export function pySlice(value: string, end: number): string {
  return Array.from(value).slice(0, end).join("");
}

/** Python の str.casefold() の近似（ドイツ語の ß などの特殊な畳み込みは扱わない）。 */
export function pyCasefold(value: string): string {
  return value.toLowerCase();
}

function dumpString(value: string): string {
  // ensure_ascii=False の json.dumps は ", \, 制御文字だけをエスケープする（JSON.stringify と同じ）。
  return JSON.stringify(value);
}

/**
 * Python の json.dumps(value, ensure_ascii=False[, sort_keys=True])。区切りは ", " と ": "。
 * 数値は整数だけを想定する（このデモのプロンプトとキャッシュキーに小数は入らない）。
 */
export function pyDumps(value: unknown, options: { sortKeys?: boolean } = {}): string {
  if (value === null || value === undefined) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return dumpString(value);
  if (Array.isArray(value)) {
    return value.length ? `[${value.map((v) => pyDumps(v, options)).join(", ")}]` : "[]";
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (options.sortKeys) entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return entries.length ? `{${entries.map(([k, v]) => `${dumpString(k)}: ${pyDumps(v, options)}`).join(", ")}}` : "{}";
}

/** datetime.now(timezone.utc).isoformat() と同じ形（マイクロ秒6桁、+00:00）。 */
export function pyUtcNow(now = new Date()): string {
  return now.toISOString().replace(/\.(\d{3})Z$/, ".$1000+00:00");
}

/** uuid4().hex */
export function uuidHex(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

/** dict.fromkeys(items) で重複を除く（最初の順序を保つ）。 */
export function uniqueInOrder<T>(items: T[]): T[] {
  return [...new Set(items)];
}
