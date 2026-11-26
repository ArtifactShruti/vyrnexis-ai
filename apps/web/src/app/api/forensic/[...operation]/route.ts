import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const api = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";
type Context = { params: Promise<{ operation: string[] }> };

function allowed(parts: string[], method: string) {
  if (!parts.every(value => /^[A-Za-z0-9_-]{1,120}$/.test(value))) return false;
  const [area, id, action, child, leaf] = parts;
  if (!["forensic-cases", "investigations"].includes(area)) return false;
  if (!id) return ["GET", "POST"].includes(method);
  if (!action) return method === "GET";
  if (area === "investigations") {
    if (action === "tasks" && leaf === "interpretations") {
      return parts.length === 5 ? ["GET", "POST"].includes(method)
        : parts.length === 7 && parts[6] === "review" && method === "POST";
    }
    if (parts.length !== 3) return false;
    return action === "report" ? method === "GET" : ["review", "cancel", "replay"].includes(action) && method === "POST";
  }
  if (parts.length === 3) {
    if (action === "assignment") return method === "PUT";
    if (action === "reports") return ["GET", "POST"].includes(method);
    return ["transition", "notes", "links", "evidence"].includes(action) && method === "POST";
  }
  if (parts.length !== 5 || !child) return false;
  if (action === "reports") return ["json", "pdf"].includes(leaf) && method === "GET";
  if (action === "notes") return leaf === "revisions" && method === "POST";
  return action === "evidence" && (leaf === "custody" && ["GET", "POST"].includes(method)
    || leaf === "export" && method === "POST");
}

async function forward(request: Request, context: Context) {
  const parts = (await context.params).operation;
  if (!allowed(parts, request.method)) return NextResponse.json({ detail: "Investigation action not found" }, { status: 404 });
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const origin = request.headers.get("origin");
    if (request.method !== "GET" && origin && new URL(origin).host !== request.headers.get("host")) {
      return NextResponse.json({ detail: "Cross-origin action rejected" }, { status: 403 });
    }
    let body: ArrayBuffer | undefined;
    if (request.body) {
      const reader = request.body.getReader();
      const bytes = new Uint8Array(64 * 1024);
      let size = 0;
      try {
        for (;;) {
          const chunk = await reader.read();
          if (chunk.done) break;
          if (size + chunk.value.length > bytes.length) {
            void reader.cancel();
            return NextResponse.json({ detail: "Investigation request exceeds 64 KiB" }, { status: 413 });
          }
          bytes.set(chunk.value, size);
          size += chunk.value.length;
        }
      } finally {
        reader.releaseLock();
      }
      body = bytes.buffer.slice(0, size);
    }
    const response = await fetch(`${api}/api/v1/${parts.join("/")}${new URL(request.url).search}`, {
      method: request.method, headers: { authorization: `Bearer ${access}`, "content-type": "application/json" },
      body, signal: AbortSignal.timeout(60000), cache: "no-store",
    });
    const headers = new Headers({
      "content-type": response.headers.get("content-type") || "application/json",
      "cache-control": "private, no-store", "x-content-type-options": "nosniff",
    });
    const disposition = response.headers.get("content-disposition");
    if (disposition) headers.set("content-disposition", disposition);
    return new Response(response.body, { status: response.status, headers });
  } catch {
    return NextResponse.json({ detail: "Investigation service unavailable" }, { status: 503 });
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
