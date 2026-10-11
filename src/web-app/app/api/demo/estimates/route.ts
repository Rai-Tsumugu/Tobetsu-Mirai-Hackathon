// GET/POST /api/demo/estimates（元: GET/POST /api/estimates）
import { queryParam, readBody, respond } from "@/lib/systems/demo/http";
import { listEstimates, saveEstimate } from "@/lib/systems/demo/service";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  return respond((db) => listEstimates(db, queryParam(request, "query", "")));
}

export function POST(request: Request) {
  return respond(async (db) => saveEstimate(db, await readBody(request)), 201);
}
