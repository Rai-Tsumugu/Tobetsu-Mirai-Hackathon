// GET /api/demo/estimates/{estimate_id}（元: GET /api/estimates/{estimate_id}）
import { respond } from "@/lib/systems/demo/http";
import { estimateDetail } from "@/lib/systems/demo/service";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, { params }: { params: Promise<{ estimateId: string }> }) {
  const { estimateId } = await params;
  return respond((db) => estimateDetail(db, estimateId));
}
