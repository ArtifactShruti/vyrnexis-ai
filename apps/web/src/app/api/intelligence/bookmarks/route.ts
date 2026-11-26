import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";

async function getAccess() {
  return (await cookies()).get("vyrnexis_access")?.value;
}

export async function GET() {
  const access = await getAccess();
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const response = await fetch(`${apiBase}/api/v1/intelligence/graph/bookmarks`, {
      headers: { authorization: `Bearer ${access}` },
      cache: "no-store",
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Bookmark service is unavailable" }, { status: 503 });
  }
}

export async function POST(request: Request) {
  const access = await getAccess();
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const response = await fetch(`${apiBase}/api/v1/intelligence/graph/bookmarks`, {
      method: "POST",
      headers: { authorization: `Bearer ${access}`, "content-type": "application/json" },
      body: await request.text(),
      cache: "no-store",
    });
    const body = await response.json();
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Bookmark service is unavailable" }, { status: 503 });
  }
}
