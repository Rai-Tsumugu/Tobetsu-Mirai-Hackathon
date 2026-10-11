// GET/POST /api/demo/cases（元: GET/POST /api/cases）
import { readBody, respond } from "@/lib/systems/demo/http";
import { createCase, listCases } from "@/lib/systems/demo/service";

export const dynamic = "force-dynamic";

export function GET() {
  return respond((db) => listCases(db));
}

export function POST(request: Request) {
  return respond(async (db) => createCase(db, await readBody(request)), 201);
}
