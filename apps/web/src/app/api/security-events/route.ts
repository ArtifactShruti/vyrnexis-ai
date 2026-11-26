import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";

export async function GET(request: Request) {
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const query = new URL(request.url).searchParams;
    const response = await fetch(`${apiBase}/api/v1/security-events?${query.toString()}`, {
      headers: { authorization: `Bearer ${access}` }, cache: "no-store",
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") || "application/json" },
    });
  } catch {
    return NextResponse.json({ detail: "Security event service is unavailable" }, { status: 503 });
  }
}

export async function POST(request: Request) {
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const identityResponse = await fetch(`${apiBase}/api/v1/auth/me`, {
      headers: { authorization: `Bearer ${access}` }, cache: "no-store",
    });
    const identity = await identityResponse.json();
    if (!identityResponse.ok) return NextResponse.json(identity, { status: identityResponse.status });
    const payload = await request.json();
    const response = await fetch(`${apiBase}/api/v1/security-events`, {
      method: "POST",
      headers: { authorization: `Bearer ${access}`, "content-type": "application/json" },
      body: JSON.stringify({ ...payload, organization_id: identity.organization.id }),
      cache: "no-store",
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Security event service is unavailable" }, { status: 503 });
  }
}
