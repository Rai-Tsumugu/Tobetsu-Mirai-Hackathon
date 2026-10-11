import { readObject, respond, withStore } from "@/lib/systems/engine/http";
import * as service from "@/lib/systems/engine/service";

export const dynamic = "force-dynamic";

export const GET = (request: Request) =>
  respond(() => {
    const raw = new URL(request.url).searchParams.get("limit");
    if (raw !== null && !/^[+-]?\d+$/.test(raw)) throw new service.HttpError(422, "limit must be an integer");
    return withStore((store) => service.listEstimates(store, raw === null ? 100 : Number(raw)));
  });

export const POST = (request: Request) =>
  respond(async () => {
    const body = await readObject(request);
    return withStore((store) => service.createEstimate(store, body));
  });
