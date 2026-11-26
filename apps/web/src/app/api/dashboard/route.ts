import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";

export async function GET() {
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const response = await fetch(`${apiBase}/api/v1/dashboard`, {
      headers: { authorization: `Bearer ${access}` },
      cache: "no-store",
    });
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") || "application/json" },
    });
  } catch {
    return NextResponse.json({ detail: "Dashboard service is unavailable" }, { status: 503 });
  }
}
