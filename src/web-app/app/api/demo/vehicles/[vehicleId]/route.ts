// GET /api/demo/vehicles/{vehicle_id}（元: GET /api/vehicles/{vehicle_id}）
import { respond } from "@/lib/systems/demo/http";
import { vehicleById } from "@/lib/systems/demo/service";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, { params }: { params: Promise<{ vehicleId: string }> }) {
  const { vehicleId } = await params;
  return respond((db) => vehicleById(db, vehicleId));
}
