// In development the Vite proxy forwards /api/* to localhost:8000, so the
// base URL is relative.  In production (Vercel) set VITE_API_BASE_URL to the
// full Cloud Run URL including the path prefix, e.g.
//   https://api-xxxxx.run.app/api/v1
const BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export function get<T>(url: string, params?: Record<string, string | undefined>) {
  const qs = params
    ? "?" +
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v!)}`)
        .join("&")
    : "";
  return request<T>(`${url}${qs}`);
}

export function post<T>(url: string, body: unknown) {
  return request<T>(url, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
