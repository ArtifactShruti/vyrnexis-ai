import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.VYRNEXIS_API_URL || "http://127.0.0.1:8001";

export async function GET() {
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const response = await fetch(`${apiBase}/api/v1/evidence`, {
      headers: { authorization: `Bearer ${access}` }, cache: "no-store",
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Evidence service is unavailable" }, { status: 503 });
  }
}

export async function POST(request: Request) {
  const access = (await cookies()).get("vyrnexis_access")?.value;
  if (!access) return NextResponse.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const identityResponse = await fetch(`${apiBase}/api/v1/auth/me`, {
      headers: { authorization: `Bearer ${access}` }, cache: "no-store",
    });
    const identity = await identityResponse.json();
    if (!identityResponse.ok) return NextResponse.json(identity, { status: identityResponse.status });
    const form = await request.formData();
    const file = form.get("file");
    if (!(file instanceof File)) return NextResponse.json({ detail: "Choose a file to upload" }, { status: 422 });
    const query = new URLSearchParams({ organization_id: identity.organization.id, name: String(form.get("name") || file.name) });
    const incidentId = String(form.get("investigation_id") || "").trim();
    if (incidentId) query.set("investigation_id", incidentId);
    const body = new FormData();
    body.set("file", file, file.name);
    const response = await fetch(`${apiBase}/api/v1/evidence?${query}`, {
      method: "POST", headers: { authorization: `Bearer ${access}` }, body, cache: "no-store",
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Evidence service is unavailable" }, { status: 503 });
  }
}
