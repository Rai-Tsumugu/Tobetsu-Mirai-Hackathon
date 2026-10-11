// Route Handler 共通: service.ts の結果を HTTP 応答にする。FastAPI の { detail } 形式に合わせる。
import { NextResponse } from "next/server";
import { withDatabase } from "../../db/client";
import { engineStore, type EngineStore } from "../../db/repositories/engine-store";
import { PyKeyError, PyTypeError, PyValueError } from "./py";
import { HttpError, type ApiResponse } from "./service";

export async function respond(fn: () => Promise<ApiResponse> | ApiResponse): Promise<NextResponse> {
  try {
    const r = await fn();
    return NextResponse.json(r.body, { status: r.status });
  } catch (e) {
    if (e instanceof HttpError) return NextResponse.json({ detail: e.detail }, { status: e.status });
    if (e instanceof PyKeyError || e instanceof PyTypeError || e instanceof PyValueError) return NextResponse.json({ detail: e.message }, { status: 422 });
    throw e;
  }
}

/** JSON 本文を読む。オブジェクトでなければ 422（FastAPI の検証エラー相当）。 */
export async function readObject(request: Request): Promise<Record<string, unknown>> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    throw new HttpError(422, "request body must be a JSON object");
  }
  if (body === null || typeof body !== "object" || Array.isArray(body)) throw new HttpError(422, "request body must be a JSON object");
  return body as Record<string, unknown>;
}

export function withStore(fn: (store: EngineStore) => Promise<ApiResponse>): Promise<ApiResponse> {
  return withDatabase((db) => fn(engineStore(db)));
}

const TRUE = ["true", "1", "yes", "on", "t", "y"];
const FALSE = ["false", "0", "no", "off", "f", "n"];
/** FastAPI の bool クエリ。解釈できなければ 422。 */
export function boolQuery(value: string | null, fallback: boolean): boolean {
  if (value === null) return fallback;
  const v = value.toLowerCase();
  if (TRUE.includes(v)) return true;
  if (FALSE.includes(v)) return false;
  throw new HttpError(422, "query parameter must be a boolean");
}
