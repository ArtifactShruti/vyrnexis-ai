import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";
type Context = { params: Promise<{ operation: string[] }> };

function backendPath(method: string, [area, id, action, extra]: string[]) {
  if (extra) return null;
  const safeId = id && /^[a-zA-Z0-9_-]{1,100}$/.test(id) ? id : null;
  if (method === "GET" && !id) {
    if (area === "rules") return "detection-rules";
    if (area === "alerts") return "security-alerts";
    if (area === "runs") return "detection-runs";
    if (area === "status") return "detection-status";
  }
  if (!safeId) return null;
  if (method === "GET" && area === "incidents" && action === "events") return `incidents/${safeId}/security-events`;
  if (method === "GET" && area === "alerts" && action === "events") return `security-alerts/${safeId}/events`;
  if (method === "PUT" && area === "rules" && !action) return `detection-rules/${safeId}`;
  if (method === "POST" && area === "alerts" && (action === "incident" || action === "false-positive")) {
    return `security-alerts/${safeId}/${action}`;
  }
  return null;
}

async function forward(request: Request, context: Context) {
  const route = backendPath(request.method, (await context.params).operation);
  if (!route) return NextResponse.json({ detail: "Detection operation not found" }, { status: 404 });
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const response = await fetch(`${apiBase}/api/v1/${route}${new URL(request.url).search}`, {
      method: request.method,
      headers: { authorization: `Bearer ${access}`, "content-type": "application/json" },
      body: request.method === "GET" ? undefined : await request.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") || "application/json", "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json({ detail: "Detection service is unavailable" }, { status: 503 });
  }
}

export const GET = forward;
export const PUT = forward;
export const POST = forward;
