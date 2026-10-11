import { readObject, respond } from "@/lib/systems/engine/http";
import * as service from "@/lib/systems/engine/service";

export const dynamic = "force-dynamic";
export const POST = (request: Request, ctx: { params: Promise<{ engineId: string }> }) =>
  respond(async () => service.calculate((await ctx.params).engineId, await readObject(request)));
