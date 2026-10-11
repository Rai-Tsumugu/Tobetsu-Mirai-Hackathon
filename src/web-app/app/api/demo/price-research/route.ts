// POST /api/demo/price-research（元: POST /api/price-research）。Simulator は固定の架空候補、live は Gemini で調査する。
import { readBody, respond } from "@/lib/systems/demo/http";
import { priceResearch } from "@/lib/systems/demo/service";

export const dynamic = "force-dynamic";
// Gemini の呼び出しは1回最大90秒で、1操作に最大2回（一時障害の再試行を含めると最大4回）かかりうる。
export const maxDuration = 300;

export function POST(request: Request) {
  return respond(async (db) => priceResearch(db, await readBody(request)));
}
