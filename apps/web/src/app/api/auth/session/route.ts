import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";

export async function GET() {
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  try {
    const response = await fetch(`${apiBase}/api/v1/auth/me`, {
      headers: { authorization: `Bearer ${access}` },
      cache: "no-store",
    });
    const body = await response.json();
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Authentication service is unavailable" }, { status: 503 });
  }
}
