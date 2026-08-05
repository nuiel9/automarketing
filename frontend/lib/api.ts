const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function apiFetch(path: string, init: RequestInit = {}): Promise<unknown> {
  const token = localStorage.getItem("am_token") ?? "";
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...((init.headers as Record<string, string>) ?? {}),
  };
  const resp = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}
