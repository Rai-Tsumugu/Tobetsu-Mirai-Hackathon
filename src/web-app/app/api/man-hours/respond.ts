// 工数見積もり API の共通処理（Route Handler ではないので、URL には現れない）。
import { DataValidationError } from "@/lib/db";
import { ValueError } from "@/lib/systems/man-hours/python-compat";

export class RequestError extends Error {}

/** リクエストの JSON を読む。読めなければ日本語メッセージの 400 にする。 */
export async function readJson(request: Request): Promise<Record<string, unknown>> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    throw new RequestError("リクエストの JSON が読めません。JSON の書き方を確認してください");
  }
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    throw new RequestError("リクエストは JSON のオブジェクトにしてください");
  }
  return body as Record<string, unknown>;
}

/** 計算に渡す入力。{ "case": {...} } でも、入力そのものでもよい。 */
export function pickCase(body: Record<string, unknown>): Record<string, unknown> {
  const candidate = "case" in body ? body.case : body;
  if (candidate === null || typeof candidate !== "object" || Array.isArray(candidate)) {
    throw new RequestError("入力（case）は JSON のオブジェクトにしてください");
  }
  return candidate as Record<string, unknown>;
}

const POSTGRES_MESSAGES: Record<string, [number, string]> = {
  "23503": [409, "DB に登録されていない作業・担当者・補正表などを参照しています"],
  "23514": [400, "DB の制約に合わない値です（人時の大小関係や範囲を確認してください）"],
  "23505": [409, "すでに同じものが登録されています"],
};

export function errorResponse(error: unknown): Response {
  if (error instanceof RequestError || error instanceof ValueError || error instanceof DataValidationError) {
    return Response.json({ status: "error", message: error.message }, { status: 400 });
  }
  const code = (error as { code?: unknown } | null)?.code;
  if (typeof code === "string" && code in POSTGRES_MESSAGES) {
    const [status, message] = POSTGRES_MESSAGES[code];
    return Response.json({ status: "error", message }, { status });
  }
  if (!process.env.DATABASE_URL) {
    return Response.json({ status: "error", message: "DB が設定されていません（DATABASE_URL）" }, { status: 503 });
  }
  return Response.json({ status: "error", message: "サーバーでエラーが発生しました。DB に接続できているか確認してください" }, { status: 503 });
}
