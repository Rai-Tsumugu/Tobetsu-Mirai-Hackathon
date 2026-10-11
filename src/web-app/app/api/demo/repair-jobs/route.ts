// GET /api/demo/repair-jobs（元: GET /api/repair-jobs）
import { respondWithoutDb } from "../../../../lib/systems/demo/http";
import { repairJobs } from "../../../../lib/systems/demo/service";

export const dynamic = "force-dynamic";

export function GET() {
  return respondWithoutDb(() => repairJobs());
}
