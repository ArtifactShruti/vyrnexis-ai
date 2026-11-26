import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const api = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";
type Context = { params: Promise<{ operation: string[] }> };
const routes: [RegExp, string[]][] = [
  [/^notifications$/, ["GET"]],
  [/^notifications\/unread-count$/, ["GET"]],
  [/^notifications\/[\w-]+\/read$/, ["POST"]],
  [/^notifications\/read-all$/, ["POST"]],
  [/^observability\/status$/, ["GET"]],
  [/^developer\/credentials$/, ["GET", "POST"]],
  [/^developer\/credentials\/[\w-]+\/revoke$/, ["POST"]],
  [/^reports$/, ["GET", "POST"]],
  [/^reports\/[\w-]+$/, ["GET"]],
  [/^reports\/[\w-]+\/export$/, ["GET"]],
  [/^commerce\/(records|transactions|totals|export)$/, ["GET"]],
  [/^commerce\/records\/[\w-]+$/, ["GET"]],
  [/^threat-indicators$/, ["GET", "POST"]],
  [/^threat-indicators\/[\w-]+$/, ["GET", "PATCH", "DELETE"]],
  [/^assets\/[\w-]+$/, ["GET", "PUT"]],
  [/^assets\/[\w-]+\/(assignment|vulnerabilities)$/, ["PUT", "POST"]],
  [/^assets\/[\w-]+\/vulnerabilities\/[\w-]+$/, ["PUT"]],
  [/^admin\/(users|audit|notifications|threat-intelligence|integrations|platform)$/, ["GET"]],
  [/^admin\/(organization|role-matrix)$/, ["GET"]],
  [/^admin\/organization$/, ["PUT"]],
  [/^admin\/users$/, ["POST"]],
  [/^admin\/users\/[\w-]+$/, ["PUT"]],
  [/^workflow-studio\/(templates|workflows|executions)$/, ["GET"]],
  [/^workflow-studio\/(workflows|validate)$/, ["POST"]],
  [/^workflow-studio\/workflows\/[\w-]+$/, ["GET", "PUT"]],
  [/^workflow-studio\/workflows\/[\w-]+\/(publish|lifecycle|executions)$/, ["POST"]],
  [/^workflow-studio\/executions\/[\w-]+$/, ["GET"]],
  [/^workflow-studio\/executions\/[\w-]+\/(cancel|replay|approvals\/[\w-]+)$/, ["POST"]],
  [/^digital-twin\/(topology|simulations)$/, ["GET"]],
  [/^digital-twin\/(dependencies|simulations)$/, ["POST"]],
  [/^digital-twin\/simulations\/[\w-]+(\/export)?$/, ["GET"]],
  [/^business-intelligence\/(report|export)$/, ["GET"]],
  [/^ai\/(settings|availability)$/, ["GET"]],
  [/^ai\/settings$/, ["PUT"]],
  [/^ai\/test$/, ["POST"]],
  [/^knowledge\/(documents|search)$/, ["GET"]],
  [/^knowledge\/documents$/, ["POST"]],
  [/^knowledge\/documents\/[\w-]+$/, ["GET", "DELETE"]],
  [/^knowledge\/documents\/[\w-]+\/versions$/, ["POST"]],
  [/^knowledge\/documents\/[\w-]+\/policy$/, ["PUT"]],
  [/^knowledge\/embeddings\/availability$/, ["GET"]],
  [/^knowledge\/documents\/[\w-]+\/embedding$/, ["GET", "POST"]],
  [/^knowledge\/search\/hybrid$/, ["POST"]],
  [/^copilot\/conversations$/, ["GET", "POST"]],
  [/^copilot\/conversations\/[\w-]+$/, ["GET", "DELETE"]],
  [/^copilot\/conversations\/[\w-]+\/export$/, ["GET"]],
  [/^copilot\/conversations\/[\w-]+\/(turns|stream|cancel\/[\w-]+)$/, ["POST"]],
];

async function forward(request: Request, context: Context) {
  const path = (await context.params).operation.join("/");
  if (!routes.some(([pattern, methods]) => pattern.test(path) && methods.includes(request.method))) {
    return NextResponse.json({ detail: "Workspace action is unavailable" }, { status: 404 });
  }
  const token = (await cookies()).get("vyrnexis_access")?.value;
  if (!token) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const origin = request.headers.get("origin");
    if (request.method !== "GET" && origin && new URL(origin).host !== request.headers.get("host")) {
      return NextResponse.json({ detail: "Cross-origin request rejected" }, { status: 403 });
    }
    let body: ArrayBuffer | undefined;
    if (request.body) {
      const limit = request.method === "POST" && path.startsWith("knowledge/") ? 3 * 1024 * 1024 : 32 * 1024;
      const bytes = new Uint8Array(limit);
      const reader = request.body.getReader();
      let length = 0;
      try {
        for (;;) {
          const chunk = await reader.read();
          if (chunk.done) break;
          if (length + chunk.value.length > limit) {
            void reader.cancel();
            return NextResponse.json({ detail: "Workspace request is too large" }, { status: 413 });
          }
          bytes.set(chunk.value, length);
          length += chunk.value.length;
        }
      } finally {
        reader.releaseLock();
      }
      body = bytes.buffer.slice(0, length);
    }
    const upstream = await fetch(`${api}/api/v1/${path}${new URL(request.url).search}`, {
      method: request.method, headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body, signal: AbortSignal.any([request.signal, AbortSignal.timeout(55_000)]), cache: "no-store",
    });
    const headers = new Headers({
      "content-type": upstream.headers.get("content-type") || "application/json",
      "cache-control": "private, no-store", "x-content-type-options": "nosniff",
    });
    const disposition = upstream.headers.get("content-disposition");
    if (disposition) headers.set("content-disposition", disposition);
    if (upstream.headers.get("content-type")?.startsWith("text/event-stream")) {
      headers.set("cache-control", "private, no-store, no-transform");
      headers.set("x-accel-buffering", "no");
    }
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    return NextResponse.json({ detail: "Workspace service unavailable" }, { status: 503 });
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const DELETE = forward;
