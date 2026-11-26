import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";
const cookieOptions = (maxAge: number) => ({
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "strict" as const,
  path: "/",
  maxAge,
});

export async function POST() {
  const store = await cookies();
  const refreshToken = store.get("vyrnexis_refresh")?.value;
  if (!refreshToken) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const response = await fetch(`${apiBase}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    });
    const body = await response.json();
    if (!response.ok) {
      return NextResponse.json({ detail: "Session expired. Please sign in again." }, { status: 401 });
    }
    const result = NextResponse.json({ user: body.user, organization: body.organization });
    result.cookies.set("vyrnexis_access", body.access_token, cookieOptions(body.expires_in || 900));
    result.cookies.set("vyrnexis_refresh", body.refresh_token, cookieOptions(7 * 24 * 60 * 60));
    return result;
  } catch {
    return NextResponse.json({ detail: "Authentication service is unavailable" }, { status: 503 });
  }
}
