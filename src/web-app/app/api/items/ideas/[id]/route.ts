// POST /api/items/ideas/M01〜M30: 各案の操作（元の POST /api/ideas/<id>）。
import { handlePost } from "@/lib/systems/items/http";
import { moduleFor } from "@/lib/systems/items/registry";

export const dynamic = "force-dynamic";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  return handlePost(request, async () => {
    const mod = await moduleFor(id);
    return { ideaId: mod.SPEC.idea_id, run: mod.run };
  });
}
