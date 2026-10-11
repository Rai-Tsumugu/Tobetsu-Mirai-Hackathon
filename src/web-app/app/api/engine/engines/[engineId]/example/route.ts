import { boolQuery, respond } from "@/lib/systems/engine/http";
import * as service from "@/lib/systems/engine/service";

export const dynamic = "force-dynamic";
export const GET = (request: Request, ctx: { params: Promise<{ engineId: string }> }) =>
  respond(async () => service.exampleRulePack((await ctx.params).engineId, boolQuery(new URL(request.url).searchParams.get("approved_rotor"), true)));
