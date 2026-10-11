import { boolQuery, respond } from "@/lib/systems/engine/http";
import * as service from "@/lib/systems/engine/service";

export const dynamic = "force-dynamic";
export const GET = (request: Request) =>
  respond(() => service.fixture(boolQuery(new URL(request.url).searchParams.get("approved_rotor"), false)));
