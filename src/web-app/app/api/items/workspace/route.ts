// POST /api/items/workspace: 統合ワークフロー（元の POST /api/workspace）。
import { handlePost } from "@/lib/systems/items/http";
import { run } from "@/lib/systems/items/integrated";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  return handlePost(request, async () => ({ ideaId: "integrated", run }));
}
