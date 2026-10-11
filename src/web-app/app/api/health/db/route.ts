import { getDatabase } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET() {
  if (!process.env.DATABASE_URL) {
    return Response.json({ status: "not_configured" }, { status: 503 });
  }

  try {
    const sql = getDatabase();
    await sql`SELECT 1`;
    return Response.json({ status: "connected" });
  } catch {
    return Response.json({ status: "unavailable" }, { status: 503 });
  }
}