import { INDEX_HTML } from "@/lib/systems/engine/ui-assets";

export const dynamic = "force-dynamic";
export const GET = () => new Response(INDEX_HTML, { headers: { "content-type": "text/html; charset=utf-8" } });
