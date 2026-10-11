// app.py の HTTP 入口の移植（Route Handler から使う）。
// 入力の検査・エラー時の 400 応答・1リクエスト1トランザクションを元と同じにする。
import { NextResponse } from "next/server";
import { withTransaction } from "../../db/client";
import { DataValidationError } from "../../db/errors";
import { InvalidOperation } from "./decimal";
import { ValidationError, type Json } from "./core";
import { PgStore } from "./pg-store";
import { NonFiniteNumberError, parseJson, toJsonValue } from "./py";

const MAX_BODY_BYTES = 4 * 1024 * 1024;

export function sendJson(status: number, value: unknown): NextResponse {
  return NextResponse.json(toJsonValue(value), {
    status,
    headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
  });
}

/** 元の画面と同じオリジンからの書き込みだけを受け付ける。 */
function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (origin === null) return true;
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const proto = request.headers.get("x-forwarded-proto") ?? new URL(request.url).protocol.replace(":", "");
  return origin === `${proto}://${host}`;
}

/** 人が直せる入力の不備（元の ValueError / TypeError / KeyError / UnicodeError → 400）。 */
function isClientError(error: unknown): error is Error {
  return (
    error instanceof ValidationError ||
    error instanceof DataValidationError ||
    error instanceof NonFiniteNumberError ||
    error instanceof SyntaxError ||
    error instanceof TypeError ||
    error instanceof RangeError ||
    (error instanceof Error && ["ValueError", "KeyError", "UnicodeError"].includes(error.name))
  );
}

/**
 * POST の共通処理。resolve は入力を読んだ後に呼ぶ（元と同じく、案IDの不備より入力の不備を先に返す）。
 */
export async function handlePost(
  request: Request,
  resolve: () => Promise<{ ideaId: string; run: (payload: unknown, store: PgStore) => Promise<unknown> }>,
): Promise<NextResponse> {
  if (!sameOrigin(request)) {
    return sendJson(403, { error: "同じ画面から操作してください" });
  }
  try {
    const body = new Uint8Array(await request.arrayBuffer());
    if (!(body.length > 0 && body.length <= MAX_BODY_BYTES)) {
      throw new ValidationError("入力サイズを確認してください（最大4MB）");
    }
    if (!(request.headers.get("content-type") ?? "").startsWith("application/json")) {
      throw new ValidationError("JSON形式の入力が必要です");
    }
    let text: string;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(body);
    } catch {
      throw new ValidationError("'utf-8' codec can't decode the request body");
    }
    const payload = parseJson(text.replace(/^﻿/, ""));
    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
      throw new ValidationError("入力は項目の集合で指定してください");
    }
    const target = await resolve();
    const result = await withTransaction((tx) => target.run(payload as Json, new PgStore(tx)));
    return sendJson(200, { mode: "simulator", idea_id: target.ideaId, result });
  } catch (error) {
    if (isClientError(error)) {
      return sendJson(400, { error: error.message, status: "要確認" });
    }
    if (error instanceof InvalidOperation) {
      // 元の実装では捕捉されない decimal の例外（応答が返らない）。画面には要確認として返す。
      return sendJson(500, { error: error.message, status: "要確認" });
    }
    console.error("items API error", error);
    return sendJson(500, { error: "サーバーで処理できませんでした", status: "要確認" });
  }
}
