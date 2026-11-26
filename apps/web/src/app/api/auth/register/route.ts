import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";
const cookieOptions = (maxAge: number) => ({
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "strict" as const,
  path: "/",
  maxAge,
});

export async function POST(request: Request) {
  try {
    const response = await fetch(`${apiBase}/api/v1/auth/register`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await request.text(),
      cache: "no-store",
    });
    const body = await response.json();
    if (!response.ok) return NextResponse.json({ detail: body.detail || "Registration failed" }, { status: response.status });

    const result = NextResponse.json({ user: body.user, organization: body.organization });
    result.cookies.set("vyrnexis_access", body.access_token, cookieOptions(body.expires_in || 900));
    result.cookies.set("vyrnexis_refresh", body.refresh_token, cookieOptions(7 * 24 * 60 * 60));
    return result;
  } catch {
    return NextResponse.json({ detail: "Authentication service is unavailable" }, { status: 503 });
  }
}
