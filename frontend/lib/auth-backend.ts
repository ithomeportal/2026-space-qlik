// Server-side calls to the FastAPI login endpoints.
//
// These deliberately bypass `/api/proxy/[...path]`: that proxy forwards the
// *session* as the identity header, and every call here happens BEFORE a session
// exists. It also runs only on the server (route handlers + the NextAuth
// `authorize`/`jwt` callbacks), so `BACKEND_URL` and `PROXY_SHARED_SECRET` are
// never exposed to the browser.
//
// Why this file exists at all: the frontend used to reach Postgres directly with
// Prisma, which put Vercel's ~23 rotating AWS egress IPs into the set of hosts
// that must be allowed through Aiven's `ip_filter` — the one blocker to removing
// `0.0.0.0/0` from an instance holding 27 databases. Vercel has no stable egress
// without the paid Secure Compute add-on, so the frontend stops touching
// Postgres instead. See /BOT/aiven-mcp/docs/SPEC-security.md.

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

// Login must not hang behind a Render cold start (30-60s) with no feedback, but
// it also must not give up before a cold start can finish. The proxy's own abort
// is 45s; issuing a code has to send mail too, so allow a little more.
const TIMEOUT_MS = 50_000

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  // Omitted when unset so local dev against a bare backend still works — the
  // backend's require_proxy is fail-open in exactly the same way.
  if (process.env.PROXY_SHARED_SECRET) {
    headers["X-Proxy-Secret"] = process.env.PROXY_SHARED_SECRET
  }
  return headers
}

export interface BackendUser {
  id: string
  email: string
  name: string | null
  department: string | null
  company: string | null
  is_active: boolean
  roles: string[]
}

async function call<T>(
  path: string,
  init: { method: "GET" | "POST"; body?: unknown },
): Promise<{ ok: true; data: T } | { ok: false; status: number; error: string }> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(`${BACKEND_URL}/api/custom/auth${path}`, {
      method: init.method,
      headers: authHeaders(),
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
      signal: controller.signal,
    })

    // A non-JSON body means we hit something that is not our API (a proxy error
    // page, an HTML 502). Treat it as a failure rather than throwing on parse.
    let payload: { data?: T; detail?: string } | null = null
    try {
      payload = await res.json()
    } catch {
      payload = null
    }

    if (!res.ok) {
      return {
        ok: false,
        status: res.status,
        error: payload?.detail ?? `Backend returned ${res.status}`,
      }
    }
    return { ok: true, data: (payload?.data ?? null) as T }
  } catch (e) {
    const aborted = e instanceof Error && e.name === "AbortError"
    return {
      ok: false,
      status: aborted ? 504 : 502,
      error: aborted ? "The server took too long to respond" : "Could not reach the server",
    }
  } finally {
    clearTimeout(timer)
  }
}

/** Issue + mail an 8-digit code. Never returns the code itself. */
export function issueLoginCode(email: string, callbackUrl = "/") {
  return call<{ sent: boolean; expires_at: string }>("/email-code/issue", {
    method: "POST",
    body: { email, callback_url: callbackUrl },
  })
}

/** Redeem a code. Returns the user NextAuth should sign in. */
export function verifyLoginCode(email: string, code: string) {
  return call<{ user: BackendUser; callback_url: string }>("/email-code/verify", {
    method: "POST",
    body: { email, code },
  })
}

/** Roles + org fields for an already-signed-in user (JWT refresh). */
export function fetchUserContext(userId: string) {
  return call<BackendUser>(`/user-context?user_id=${encodeURIComponent(userId)}`, {
    method: "GET",
  })
}
