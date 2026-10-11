// POST /api/man-hours/estimate  入力 JSON を受けて計算結果を返す（保存しない）。
// DB が使えるときは DB の現行パラメータ・採用中の補正表・実績で、使えないときは同梱の JSON で計算する。
import { loadReference } from "@/lib/db/repositories/man-hours-store";
import { estimateSafely, toMarkdown } from "@/lib/systems/man-hours/estimator";
import { errorResponse, pickCase, readJson } from "../respond";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const caseData = pickCase(await readJson(request));
    const reference = await loadReference();
    const result = estimateSafely(caseData, reference.params, reference.catalog, reference.records);
    return Response.json({
      status: "ok",
      source: reference.source,
      fallback_reason: reference.fallbackReason ?? null,
      adopted_rate_table: reference.params.adopted_rate_table,
      result,
      markdown: toMarkdown(result),
    });
  } catch (error) {
    return errorResponse(error);
  }
}
