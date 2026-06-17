import { auth } from "@/lib/auth"
import { NextRequest, NextResponse } from "next/server"

export const maxDuration = 60

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

const RETRYABLE_STATUS = new Set([502, 503, 504])
const RETRY_DELAYS_MS = [5000, 10000]

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function proxyRequest(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const session = await auth()
  if (!session?.user) {
    return NextResponse.json({ success: false, error: "Unauthorized" }, { status: 401 })
  }

  const { path } = await params
  const pathStr = path.join("/")
  const backendUrl = new URL(`/api/${pathStr}`, BACKEND_URL)

  // Use append (not set) so repeated query params survive. Multi-select
  // filters serialize as `?customer_ids=A&customer_ids=B`; `.set()` would
  // collapse them to the last value, breaking include/exclude scope.
  req.nextUrl.searchParams.forEach((value, key) => {
    backendUrl.searchParams.append(key, value)
  })

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${JSON.stringify({
      sub: session.user.id,
      email: session.user.email,
      name: session.user.name,
      roles: session.user.roles ?? [],
      department: session.user.department,
      company: session.user.company,
    })}`,
  }

  let body: string | undefined
  if (req.method !== "GET" && req.method !== "HEAD") {
    try {
      const raw = await req.text()
      if (raw) body = raw
    } catch {
      // No body
    }
  }

  const maxAttempts = req.method === "GET" ? RETRY_DELAYS_MS.length + 1 : 1
  const started = Date.now()
  let lastStatus = 0

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 45000)
    try {
      const res = await fetch(backendUrl.toString(), {
        method: req.method,
        headers,
        body,
        signal: controller.signal,
      })
      clearTimeout(timeout)
      lastStatus = res.status

      if (RETRYABLE_STATUS.has(res.status) && attempt < maxAttempts - 1) {
        console.warn(
          `[proxy] ${req.method} ${pathStr} → ${res.status} attempt ${attempt + 1}/${maxAttempts}, retrying in ${RETRY_DELAYS_MS[attempt]}ms`,
        )
        await sleep(RETRY_DELAYS_MS[attempt])
        continue
      }

      // Pass through non-JSON bodies untouched (CSV downloads, files, etc.)
      const contentType = res.headers.get("content-type") || ""
      if (!contentType.includes("application/json")) {
        const body = await res.arrayBuffer()
        const passHeaders = new Headers()
        if (contentType) passHeaders.set("Content-Type", contentType)
        const cd = res.headers.get("content-disposition")
        if (cd) passHeaders.set("Content-Disposition", cd)
        return new NextResponse(body, { status: res.status, headers: passHeaders })
      }

      const data = await res.json().catch(() => ({
        success: false,
        error: `Backend responded ${res.status}`,
      }))

      if (!res.ok) {
        const duration = Date.now() - started
        console.warn(
          `[proxy] ${req.method} ${pathStr} → ${res.status} after ${duration}ms (attempts=${attempt + 1})`,
        )
      }

      const response = NextResponse.json(data, { status: res.status })
      if (res.status === 503) response.headers.set("Retry-After", "30")
      return response
    } catch (err) {
      clearTimeout(timeout)
      const isAbort = err instanceof Error && err.name === "AbortError"
      // Only retry genuine network errors (connection refused during a cold
      // start, etc.) — NOT a 45s abort. An aborted request already consumed a
      // scarce backend connection for the full window; retrying the same slow
      // query 2× more just multiplies load on the exact endpoints that are
      // already starving the pool. Fail fast and let React Query retry later.
      if (!isAbort && attempt < maxAttempts - 1) {
        console.warn(
          `[proxy] ${req.method} ${pathStr} network error (fetch) attempt ${attempt + 1}, retrying`,
        )
        await sleep(RETRY_DELAYS_MS[attempt])
        continue
      }
      if (isAbort) {
        const duration = Date.now() - started
        console.warn(
          `[proxy] ${req.method} ${pathStr} → aborted after ${duration}ms (no retry)`,
        )
        return NextResponse.json(
          { success: false, error: "Backend timed out — please retry shortly" },
          { status: 504, headers: { "Retry-After": "10" } },
        )
      }
      const duration = Date.now() - started
      console.warn(
        `[proxy] ${req.method} ${pathStr} → unreachable after ${duration}ms (lastStatus=${lastStatus})`,
      )
      return NextResponse.json(
        { success: false, error: "Backend unavailable — please retry shortly" },
        { status: 503, headers: { "Retry-After": "30" } },
      )
    }
  }

  return NextResponse.json(
    { success: false, error: "Backend unavailable — please retry shortly" },
    { status: 503, headers: { "Retry-After": "30" } },
  )
}

export const GET = proxyRequest
export const POST = proxyRequest
export const PATCH = proxyRequest
export const DELETE = proxyRequest
