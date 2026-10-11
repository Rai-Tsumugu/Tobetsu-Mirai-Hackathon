// GET /api/items/ideas: 30案の名称・説明・架空の既定入力（元の GET /api/ideas）。
import { sendJson } from "@/lib/systems/items/http";
import { specifications } from "@/lib/systems/items/registry";

export const dynamic = "force-dynamic";

export function GET() {
  return sendJson(200, { mode: "simulator", ideas: specifications() });
}
