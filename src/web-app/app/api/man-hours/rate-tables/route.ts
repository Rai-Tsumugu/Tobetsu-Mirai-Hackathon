// GET /api/man-hours/rate-tables  DB にある補正表の版と状態（候補・採用・退役）。DB がなければ空。
import { withDatabase } from "@/lib/db";
import { listRateTables } from "@/lib/db/repositories/man-hours-store";
import { errorResponse } from "../respond";

export const dynamic = "force-dynamic";

export async function GET() {
  if (!process.env.DATABASE_URL) {
    return Response.json({ status: "ok", source: "json", tables: [] });
  }
  try {
    const tables = await withDatabase((db) => listRateTables(db));
    return Response.json({ status: "ok", source: "database", tables });
  } catch (error) {
    return errorResponse(error);
  }
}
