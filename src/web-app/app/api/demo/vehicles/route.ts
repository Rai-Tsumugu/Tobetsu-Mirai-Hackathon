// GET/POST /api/demo/vehicles（元: GET/POST /api/vehicles）
import { queryParam, readBody, respond } from "../../../../lib/systems/demo/http";
import { createManualVehicle, listVehicles } from "../../../../lib/systems/demo/service";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  return respond((db) => listVehicles(db, queryParam(request, "query", ""), queryParam(request, "origin", "all")));
}

export function POST(request: Request) {
  return respond(async (db) => createManualVehicle(db, await readBody(request)), 201);
}
