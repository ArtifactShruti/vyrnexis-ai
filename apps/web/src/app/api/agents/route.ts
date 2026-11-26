import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";

async function accessToken() {
  return (await cookies()).get("vyrnexis_access")?.value;
}

export async function GET(request: Request) {
  const access = await accessToken();
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  const url = new URL(request.url);
  const endpoint = url.searchParams.get("view") === "history" ? "/api/v1/agents/executions" : "/api/v1/agents";
  try {
    const response = await fetch(`${apiBase}${endpoint}`, {
      headers: { authorization: `Bearer ${access}` }, cache: "no-store",
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Agent service is unavailable" }, { status: 503 });
  }
}

export async function POST(request: Request) {
  const access = await accessToken();
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const response = await fetch(`${apiBase}/api/v1/agents/executions`, {
      method: "POST",
      headers: { authorization: `Bearer ${access}`, "content-type": "application/json" },
      body: JSON.stringify(await request.json()), cache: "no-store",
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Agent service is unavailable" }, { status: 503 });
  }
}
