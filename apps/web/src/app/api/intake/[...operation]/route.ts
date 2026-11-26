import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";
const SAFE = /^[a-zA-Z0-9_-]{1,100}$/;
const MAX_BODY = 512 * 1024;
type Context = { params: Promise<{ operation: string[] }> };

function backendPath(path: string[], method: string) {
  if (!path.every(part => SAFE.test(part))) return null;
  const [area, id, section, record, action] = path;
  if (area === "data-sources") {
    if (path.length === 1 && ["GET", "POST"].includes(method)) return area;
    if (path.length === 3 && ["batches", "keys"].includes(section) && ["GET", "POST"].includes(method)) return path.join("/");
    if (path.length === 4 && section === "batches" && method === "GET") return path.join("/");
    if (path.length === 5 && section === "keys" && action === "revoke" && method === "POST") return path.join("/");
  }
  if (area === "commerce") {
    if (path.length === 2 && ["records", "totals", "findings", "policy"].includes(id) && method === "GET") return path.join("/");
    if (path.length === 2 && id === "policy" && method === "PUT") return path.join("/");
    if (path.length === 4 && id === "findings" && record === "sources" && method === "GET") return path.join("/");
    if (path.length === 4 && id === "findings" && record === "scenarios" && ["GET", "POST"].includes(method)) return path.join("/");
    if (path.length === 4 && id === "findings" && ["dismiss", "incident"].includes(record) && method === "POST") return path.join("/");
    if (path.length === 4 && id === "refunds" && record === "evaluate" && method === "POST") return path.join("/");
  }
  if (area === "evidence" && path.length === 3) {
    if (section === "activity" && method === "GET") return path.join("/");
    if (section === "verify" && method === "POST") return path.join("/");
  }
  return null;
}

async function forward(request: Request, context: Context) {
  const path = backendPath((await context.params).operation, request.method);
  if (!path) return NextResponse.json({ detail: "Intake operation not found" }, { status: 404 });
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const origin = request.headers.get("origin");
    if (request.method !== "GET" && origin && new URL(origin).host !== request.headers.get("host")) {
      return NextResponse.json({ detail: "Cross-origin request rejected" }, { status: 403 });
    }
    let body: ArrayBuffer | undefined;
    if (request.body) {
      const reader = request.body.getReader();
      const target = new Uint8Array(MAX_BODY);
      let length = 0;
      try {
        for (;;) {
          const part = await reader.read();
          if (part.done) break;
          if (length + part.value.byteLength > MAX_BODY) {
            await reader.cancel();
            return NextResponse.json({ detail: "Upload exceeds 512 KiB" }, { status: 413 });
          }
          target.set(part.value, length);
          length += part.value.byteLength;
        }
      } finally {
        reader.releaseLock();
      }
      body = target.buffer.slice(0, length);
    }
    const headers = new Headers({
      authorization: `Bearer ${access}`,
      "content-type": request.headers.get("content-type") || "application/json",
    });
    const idempotencyKey = request.headers.get("idempotency-key");
    if (idempotencyKey) headers.set("idempotency-key", idempotencyKey);
    const response = await fetch(`${apiBase}/api/v1/${path}${new URL(request.url).search}`, {
      method: request.method, headers, body, cache: "no-store", signal: AbortSignal.timeout(30000),
    });
    return new Response(await response.text(), { status: response.status, headers: {
      "content-type": response.headers.get("content-type") || "application/json", "cache-control": "no-store",
    }});
  } catch {
    return NextResponse.json({ detail: "Intake service is unavailable" }, { status: 503 });
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
