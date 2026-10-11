// POST /api/man-hours/estimates  入力を保存して計算し、結果を追記する（DB が必要）。
// GET  /api/man-hours/estimates?caseId=...  保存済みの最新の計算結果を返す。
import { withDatabase } from "@/lib/db";
import { estimateAndSave, getSavedEstimate } from "@/lib/db/repositories/man-hours-store";
import { errorResponse, pickCase, readJson, RequestError } from "../respond";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = await readJson(request);
    const caseData = pickCase(body);
    const createdBy = typeof body.createdBy === "string" && body.createdBy.trim() ? body.createdBy.trim() : null;
    const saved = await withDatabase((db) => estimateAndSave(db, caseData, { createdBy }));
    return Response.json({ status: "ok", estimate_id: saved.estimateId, result: saved.result }, { status: 201 });
  } catch (error) {
    return errorResponse(error);
  }
}

export async function GET(request: Request) {
  try {
    const caseId = new URL(request.url).searchParams.get("caseId");
    if (!caseId) {
      throw new RequestError("caseId を指定してください");
    }
    const saved = await withDatabase((db) => getSavedEstimate(db, caseId));
    if (!saved) {
      return Response.json({ status: "error", message: `保存済みの結果がありません: ${caseId}` }, { status: 404 });
    }
    return Response.json({ status: "ok", estimate_id: saved.estimateId, created_at: saved.createdAt, result: saved.result });
  } catch (error) {
    return errorResponse(error);
  }
}
