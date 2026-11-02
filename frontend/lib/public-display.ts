/**
 * Public displays — read-only report views for the floor TVs (2026-11-02).
 *
 * SERVER ONLY. Imported by server components under `app/public/` and nowhere
 * else: it reads `PUBLIC_DISPLAY_KEYS` and `PROXY_SHARED_SECRET`, which must
 * never reach a browser bundle (`backend/tests/test_public_display.py` checks
 * no `"use client"` file imports it).
 *
 * THE GATE
 * --------
 * A TV opens `/public/<slug>?key=<display key>`. No user login exists here:
 *   1. `isValidDisplayKey()` compares the key against `PUBLIC_DISPLAY_KEYS`
 *      (comma-separated ⇒ one key per location, rotated one at a time). Unset
 *      or empty ⇒ EVERY key is refused (fail-closed).
 *   2. A refused key renders a plain 404 — the page never admits it exists.
 *   3. Only then does the SERVER fetch the backend, proving itself with
 *      `X-Proxy-Secret`. The browser never talks to the backend, and the
 *      backend route is fail-closed on that secret too.
 *
 * Adding a display = one `PUBLIC_DISPLAYS` entry + a page + a backend route
 * with an explicit field allowlist (docs/SPEC-PUBLIC-DISPLAY.md).
 */
import { createHash, timingSafeEqual } from "crypto"

export const PUBLIC_DISPLAYS = {
  "booker-rank": {
    title: "Booker Rank",
    backendPath: "/api/public/booker-rank",
  },
} as const

export type PublicDisplaySlug = keyof typeof PUBLIC_DISPLAYS

/** Every page re-renders on this cadence (client `router.refresh()`). */
export const PUBLIC_DISPLAY_REFRESH_MS = 5 * 60 * 1000

const FETCH_TIMEOUT_MS = 25_000
const RETRY_DELAY_MS = 5_000
const MIN_KEY_LENGTH = 24

function digest(value: string): Buffer {
  return createHash("sha256").update(value, "utf8").digest()
}

/** The configured keys. Short entries are ignored so a typo like `x` can
 *  never become a valid key. Pure on its input — exported for tests. */
export function parseDisplayKeys(raw: string | undefined): string[] {
  return (raw ?? "")
    .split(",")
    .map((k) => k.trim())
    .filter((k) => k.length >= MIN_KEY_LENGTH)
}

/** Constant-time: both sides are hashed to equal length first, and every
 *  configured key is compared (no early exit on a match). */
export function isValidDisplayKey(
  candidate: string | string[] | undefined,
  raw: string | undefined = process.env.PUBLIC_DISPLAY_KEYS,
): boolean {
  if (typeof candidate !== "string" || candidate.length === 0) return false
  const keys = parseDisplayKeys(raw)
  if (keys.length === 0) return false
  const given = digest(candidate)
  return keys.reduce((ok, key) => timingSafeEqual(given, digest(key)) || ok, false)
}

export type DisplayFetch<T> =
  | { ok: true; data: T; fetchedAt: string }
  | { ok: false; reason: string }

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function fetchOnce(url: string, secret: string): Promise<Response> {
  return fetch(url, {
    headers: { "X-Proxy-Secret": secret },
    cache: "no-store",
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  })
}

/** Server-to-server fetch of one display's payload. Never throws: a TV must
 *  keep showing a "retrying" state rather than an error page it cannot leave.
 *  One retry covers a Render cold start (the proxy's rule: GET 502/503/504). */
export async function fetchPublicDisplay<T>(slug: PublicDisplaySlug): Promise<DisplayFetch<T>> {
  const secret = process.env.PROXY_SHARED_SECRET
  if (!secret) return { ok: false, reason: "Display not configured" }
  const base = process.env.BACKEND_URL || "http://localhost:8000"
  const url = new URL(PUBLIC_DISPLAYS[slug].backendPath, base).toString()

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const res = await fetchOnce(url, secret)
      if (res.ok) {
        const body = (await res.json()) as { success?: boolean; data?: T }
        if (body.success && body.data) {
          return { ok: true, data: body.data, fetchedAt: new Date().toISOString() }
        }
        return { ok: false, reason: "Unexpected response" }
      }
      if (![502, 503, 504].includes(res.status)) {
        console.warn(`[public-display] ${slug}: backend answered ${res.status}`)
        return { ok: false, reason: `Backend ${res.status}` }
      }
    } catch (err) {
      console.warn(`[public-display] ${slug}: fetch failed`, err)
    }
    if (attempt === 0) await sleep(RETRY_DELAY_MS)
  }
  return { ok: false, reason: "Data source waking up" }
}
