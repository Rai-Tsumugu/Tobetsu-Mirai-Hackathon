import { BROWSER_MJS } from "@/lib/systems/engine/ui-assets";

export const dynamic = "force-dynamic";
export const GET = () => new Response(BROWSER_MJS, { headers: { "content-type": "text/javascript; charset=utf-8" } });
