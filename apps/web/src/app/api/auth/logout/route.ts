import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";

export async function POST() {
  const store = await cookies();
  const refreshToken = store.get("vyrnexis_refresh")?.value;
  let status = 200;
  if (refreshToken) {
    try {
      const response = await fetch(`${apiBase}/api/v1/auth/logout`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: "no-store",
      });
      if (!response.ok) status = response.status;
    } catch {
      status = 503;
    }
  }
  const result = NextResponse.json({ signed_out: status === 200 }, { status });
  result.cookies.delete("vyrnexis_access");
  result.cookies.delete("vyrnexis_refresh");
  return result;
}
