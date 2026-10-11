import { respond, withStore } from "@/lib/systems/engine/http";
import * as service from "@/lib/systems/engine/service";

export const dynamic = "force-dynamic";
export const GET = (_request: Request, ctx: { params: Promise<{ estimateId: string }> }) =>
  respond(async () => {
    const { estimateId } = await ctx.params;
    return withStore((store) => service.getEstimate(store, estimateId));
  });
