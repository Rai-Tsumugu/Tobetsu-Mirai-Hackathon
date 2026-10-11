/**
 * 辞書のキーの並びを reference（同梱の JSON）に合わせる。
 * PostgreSQL の jsonb はキーの順を保たないが、エンジンには並びで結果が決まる辞書がある
 * （音声メモの語の辞書、締結部の錆の区分の前方一致、重量の状態の前方一致、一覧表示の順）。
 * reference にないキーは、受け取った順のまま後ろに付ける。配列は同じ位置の要素どうしを対応させる。
 */
export function restoreKeyOrder<T>(value: T, reference: unknown): T {
  if (Array.isArray(value)) {
    const refItems = Array.isArray(reference) ? reference : [];
    return value.map((item, index) => restoreKeyOrder(item, refItems[index])) as T;
  }
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const refRecord =
      reference !== null && typeof reference === "object" && !Array.isArray(reference)
        ? (reference as Record<string, unknown>)
        : {};
    const known = Object.keys(refRecord).filter((key) => key in record);
    const unknown = Object.keys(record).filter((key) => !(key in refRecord));
    return Object.fromEntries([...known, ...unknown].map((key) => [key, restoreKeyOrder(record[key], refRecord[key])])) as T;
  }
  return value;
}
