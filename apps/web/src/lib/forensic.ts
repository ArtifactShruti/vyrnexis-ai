export async function forensic<T>(path: string, options?: RequestInit): Promise<T> {
  const result = await fetch(`/api/forensic/${path}`, { ...options, cache: "no-store" });
  const body = await result.json();
  if (!result.ok) throw new Error(typeof body.detail === "string" ? body.detail : "The investigation request is invalid.");
  return body as T;
}

export function forensicBody(method: "POST" | "PUT", value: object): RequestInit {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(value) };
}

export const caseWriters = ["owner", "organization_admin", "forensic_investigator"];
export const caseAdmins = ["owner", "organization_admin"];

export async function sessionRole(signal?: AbortSignal) {
  const result = await fetch("/api/auth/session", { cache: "no-store", signal });
  if (!result.ok) throw new Error("Sign in to view your organization’s investigations.");
  const body = await result.json();
  return body.user.role as string;
}

export function localTime(value: string) {
  return new Date(value).toLocaleString();
}
