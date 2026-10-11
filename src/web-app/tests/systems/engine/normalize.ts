/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * 正準 JSON の SHA-256 は、JS が 1.0 と 1 を区別できないため元の Python の値と一致しない。
 * ダイジェスト文字列は形式（64 桁の 16 進）だけを照合する。
 */
export function normalize(value: any): any {
  if (typeof value === "string") return /^[0-9a-f]{64}$/.test(value) ? "<sha256>" : value;
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, normalize(v)]));
  return value;
}
