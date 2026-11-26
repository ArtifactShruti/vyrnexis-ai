import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const api = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";

export async function PUT(request: Request, context: { params: Promise<{ incidentId: string }> }) {
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  const incidentId = (await context.params).incidentId;
  const payload = await request.json();
  const upstream = await fetch(`${api}/api/v1/incidents/${encodeURIComponent(incidentId)}/assignment`, {
    method: "PUT",
    headers: { authorization: `Bearer ${access}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return NextResponse.json(await upstream.json(), { status: upstream.status });
}
