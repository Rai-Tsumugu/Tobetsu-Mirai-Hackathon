import { readObject, respond } from "@/lib/systems/engine/http";
import * as service from "@/lib/systems/engine/service";

export const dynamic = "force-dynamic";
export const POST = (request: Request) => respond(async () => service.compare(await readObject(request)));
