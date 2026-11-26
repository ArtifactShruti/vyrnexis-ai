import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";

export async function GET(_request: Request, context: { params: Promise<{ evidenceId: string }> }) {
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  const { evidenceId } = await context.params;
  try {
    const response = await fetch(`${apiBase}/api/v1/evidence/${encodeURIComponent(evidenceId)}/download`, {
      headers: { authorization: `Bearer ${access}` }, cache: "no-store",
    });
    if (!response.ok) return NextResponse.json(await response.json(), { status: response.status });
    return new Response(response.body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") || "application/octet-stream",
        "content-disposition": response.headers.get("content-disposition") || "attachment",
        "cache-control": "private, no-store",
        "x-content-type-options": "nosniff",
      },
    });
  } catch {
    return NextResponse.json({ detail: "Evidence service is unavailable" }, { status: 503 });
  }
}
