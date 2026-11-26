import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";

export async function PATCH(request: Request, context: { params: Promise<{ eventId: string }> }) {
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  const { eventId } = await context.params;
  try {
    const response = await fetch(`${apiBase}/api/v1/security-events/${encodeURIComponent(eventId)}/status`, {
      method: "PATCH",
      headers: { authorization: `Bearer ${access}`, "content-type": "application/json" },
      body: await request.text(),
      cache: "no-store",
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Security event service is unavailable" }, { status: 503 });
  }
}
