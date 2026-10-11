import { respond } from "@/lib/systems/engine/http";
import * as service from "@/lib/systems/engine/service";

export const dynamic = "force-dynamic";
export const GET = (request: Request) => respond(() => service.integratedSchema(new URL(request.url).searchParams.get("job_id") ?? undefined));
