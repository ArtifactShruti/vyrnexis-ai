export async function intake<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/intake/${path}`, { cache: "no-store", ...options });
  const body = await response.json();
  if (!response.ok) {
    if (response.status === 401) throw new Error("Your session has expired. Sign in again.");
    throw new Error(typeof body.detail === "string" ? body.detail : "The submitted request was invalid.");
  }
  return body as T;
}

export function jsonRequest(method: "POST" | "PUT", value: object): RequestInit {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(value) };
}

export function displayDate(value: string) {
  return new Date(value).toLocaleString();
}
