// PUT /api/demo/cases/{case_id}（元: PUT /api/cases/{case_id}）
import { readBody, respond } from "@/lib/systems/demo/http";
import { updateCase } from "@/lib/systems/demo/service";

export const dynamic = "force-dynamic";

export async function PUT(request: Request, { params }: { params: Promise<{ caseId: string }> }) {
  const { caseId } = await params;
  return respond(async (db) => updateCase(db, caseId, await readBody(request)));
}
