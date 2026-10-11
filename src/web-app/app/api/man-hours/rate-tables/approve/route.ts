// POST /api/man-hours/rate-tables/approve  { "rateTable": "v2", "approvedBy": "mechanic-demo-01" }
// 整備士の承認で、採用中の補正表を切り替える。DB にまだない版は、候補として作ってから採用する。
import { withDatabase } from "@/lib/db";
import { approveRateTable } from "@/lib/db/repositories/man-hours-store";
import { errorResponse, readJson, RequestError } from "../../respond";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = await readJson(request);
    if (typeof body.rateTable !== "string") {
      throw new RequestError("rateTable（採用する補正表の版。例: v2）を指定してください");
    }
    const approvedBy = typeof body.approvedBy === "string" ? body.approvedBy : "";
    const approved = await withDatabase((db) => approveRateTable(db, body.rateTable as string, approvedBy));
    return Response.json({ status: "ok", ...approved });
  } catch (error) {
    return errorResponse(error);
  }
}
