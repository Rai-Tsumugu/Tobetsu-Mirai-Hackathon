// GET /api/demo/config（元: GET /api/config）。Gemini のキーが設定済みかだけを返す（キーは返さない）。
import { respondWithoutDb } from "@/lib/systems/demo/http";
import { config } from "@/lib/systems/demo/service";

export const dynamic = "force-dynamic";

export function GET() {
  return respondWithoutDb(() => config());
}
