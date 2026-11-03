/**
 * Same-origin API client. Session is an httpOnly cookie; unsafe methods send the double-submit CSRF token.
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

export const API_BASE = "/api/v1";

/** Set while a platform admin views a customer's account, so an expired view returns to the admin, not to /login. */
export const VIEWING_KEY = "rasd-viewing-as";

export function setViewing(on: boolean) {
  try {
    if (on) sessionStorage.setItem(VIEWING_KEY, "1");
    else sessionStorage.removeItem(VIEWING_KEY);
  } catch {
    /* storage blocked: an expired view then falls back to the login page */
  }
}

function isViewing(): boolean {
  try {
    return sessionStorage.getItem(VIEWING_KEY) === "1";
  } catch {
    return false;
  }
}

/** Go back to the admin's own session (also works once the 30-minute view has expired). */
export async function stopViewing(): Promise<{ user_id: string | null; signed_out: boolean }> {
  const res = await fetch(`${API_BASE}/auth/impersonation/stop`, {
    method: "POST",
    headers: { Accept: "application/json", "X-CSRF-Token": readCookie("lh_csrf") ?? "" },
    credentials: "same-origin",
  });
  setViewing(false);
  if (!res.ok) return { user_id: null, signed_out: true };
  return res.json();
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

type Query = Record<string, string | number | boolean | null | undefined>;

export function buildQuery(params?: Query): string {
  if (!params) return "";
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown; query?: Query; signal?: AbortSignal } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const csrf = readCookie("lh_csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  const res = await fetch(`${API_BASE}${path}${buildQuery(init.query)}`, {
    method,
    headers,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    credentials: "same-origin",
    signal: init.signal,
  });
  if (!res.ok) {
    let code = "http_error";
    let message = res.statusText || "Request failed";
    let details: unknown;
    try {
      const data = await res.json();
      code = data?.error?.code ?? code;
      message = data?.error?.message ?? message;
      details = data?.error?.details;
    } catch {
      /* non-JSON error body */
    }
    const onAuthPage = typeof window !== "undefined" && ["/login", "/register", "/forgot-password", "/reset-password", "/verify-email"].some((p) => window.location.pathname.startsWith(p));
    if (res.status === 401 && typeof window !== "undefined" && !onAuthPage) {
      if (isViewing()) {
        // The read-only view of a customer ran out: return to the admin's own account.
        const r = await stopViewing();
        window.location.assign(r.signed_out ? `${window.location.origin}/login` : `${window.location.origin}/app/admin?tab=users${r.user_id ? `&user=${r.user_id}` : ""}`);
        throw new ApiError(res.status, code, message, details);
      }
      // Outside React: a hard navigation also clears all client caches for the expired session.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    }
    throw new ApiError(res.status, code, message, details);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Trigger a file download for an authenticated GET endpoint. */
export async function download(path: string, query?: Query, fallbackName = "export") {
  const res = await fetch(`${API_BASE}${path}${buildQuery(query)}`, { credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, "download_failed", "Download failed");
  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") ?? "";
  const name = /filename="?([^"]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
