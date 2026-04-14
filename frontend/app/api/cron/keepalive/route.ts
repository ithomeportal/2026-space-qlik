import { NextResponse } from "next/server"

export const maxDuration = 60
export const dynamic = "force-dynamic"

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

export async function GET() {
  const started = Date.now()
  try {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 55000)
    const res = await fetch(`${BACKEND_URL}/api/health`, {
      signal: controller.signal,
      cache: "no-store",
    })
    clearTimeout(timeout)
    const duration = Date.now() - started
    console.log(`[keepalive] backend /api/health → ${res.status} in ${duration}ms`)
    return NextResponse.json({
      success: true,
      backend_status: res.status,
      duration_ms: duration,
    })
  } catch (err) {
    const duration = Date.now() - started
    const msg = err instanceof Error ? err.message : String(err)
    console.warn(`[keepalive] backend unreachable after ${duration}ms: ${msg}`)
    return NextResponse.json(
      { success: false, error: msg, duration_ms: duration },
      { status: 503 },
    )
  }
}
