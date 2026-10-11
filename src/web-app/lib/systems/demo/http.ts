// Route Handler の共通処理。FastAPI と同じく、エラーは {"detail": ...} の JSON で返す。
import { withDatabase, type Database } from "@/lib/db";
import { HttpError, parsePyJson } from "./py";

/** リクエストボディを Python の json.loads と同じ規則で読む。読めなければ FastAPI と同じ 422。 */
export async function readBody(request: Request): Promise<unknown> {
  const text = await request.text();
  if (!text) throw new HttpError(422, [{ type: "missing", loc: ["body"], msg: "Field required", input: null }]);
  try {
    return parsePyJson(text);
  } catch {
    throw new HttpError(422, [{ type: "json_invalid", loc: ["body", 0], msg: "JSON decode error", input: {} }]);
  }
}

/** クエリ文字列の値（同じ名前が複数あれば FastAPI と同じく最後のもの）。 */
export function queryParam(request: Request, name: string, fallback: string): string {
  const values = new URL(request.url).searchParams.getAll(name);
  return values.length ? values[values.length - 1] : fallback;
}

/** DB 接続を開いて処理し、結果を JSON で返す。 */
export async function respond(fn: (db: Database) => Promise<unknown> | unknown, status = 200): Promise<Response> {
  try {
    return Response.json(await withDatabase(async (db) => fn(db)), { status });
  } catch (error) {
    if (error instanceof HttpError) return Response.json({ detail: error.detail }, { status: error.status });
    console.error(error);
    return new Response("Internal Server Error", { status: 500, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }
}

/** DB を使わない API 用。 */
export async function respondWithoutDb(fn: () => unknown): Promise<Response> {
  try {
    return Response.json(await fn());
  } catch (error) {
    if (error instanceof HttpError) return Response.json({ detail: error.detail }, { status: error.status });
    console.error(error);
    return new Response("Internal Server Error", { status: 500, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }
}
