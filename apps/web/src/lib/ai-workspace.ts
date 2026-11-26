export type Citation = { key: string; kind: string; title: string; excerpt: string; href: string; version?: number; location?: string; document_id?: string };
export type Availability = { mode: string; provider: string; model: string | null; available: boolean };

export async function workspace<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/workspace/${path}`, { cache: "no-store", ...init });
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("Sign-in required.");
  }
  if (response.status === 204) return undefined as T;
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Check the submitted values.");
  return result as T;
}

export function request(method: "POST" | "PUT", value?: object): RequestInit {
  return { method, ...(value ? { headers: { "content-type": "application/json" }, body: JSON.stringify(value) } : {}) };
}
