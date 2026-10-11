import { readObject, respond, withStore } from "@/lib/systems/engine/http";
import * as service from "@/lib/systems/engine/service";

export const dynamic = "force-dynamic";
export const POST = (request: Request, ctx: { params: Promise<{ scenarioId: string }> }) =>
  respond(async () => {
    const { scenarioId } = await ctx.params;
    const body = await readObject(request);
    return withStore((store) => service.addObservationEvent(store, scenarioId, body));
  });
