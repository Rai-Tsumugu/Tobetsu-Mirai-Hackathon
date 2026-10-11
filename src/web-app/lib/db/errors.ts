/**
 * 人が入力や選択を直す必要があるときのエラー。0 や既定値で黙って置き換えない。
 * message は画面にそのまま出せる日本語にする。
 */
export class DataValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DataValidationError";
  }
}

export function requireText(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new DataValidationError(`${field}: 入力が必要です`);
  }
  return value.trim();
}

const DECIMAL_PATTERN = /^\d+(\.\d+)?$/;

/** 非負の有限な10進数を、丸めずに文字列で返す（numeric 列へそのまま渡す）。 */
export function requireDecimal(value: unknown, field: string, options: { positive?: boolean } = {}): string {
  const text = typeof value === "number" ? (Number.isFinite(value) ? String(value) : "") : value;
  if (typeof text !== "string" || !DECIMAL_PATTERN.test(text.trim())) {
    throw new DataValidationError(`${field}: 有限の正数/非負数を入力してください`);
  }
  const normalized = text.trim();
  if (options.positive && Number(normalized) === 0) {
    throw new DataValidationError(`${field}: 0 より大きい数値を入力してください`);
  }
  return normalized;
}
