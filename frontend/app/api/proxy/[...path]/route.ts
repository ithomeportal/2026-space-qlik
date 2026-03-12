import { auth } from "@/lib/auth"
import { NextRequest, NextResponse } from "next/server"

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

async function proxyRequest(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const session = await auth()
  if (!session?.user) {
    return NextResponse.json({ success: false, error: "Unauthorized" }, { status: 401 })
  }

  const { path } = await params
  const backendUrl = new URL(`/api/${path.join("/")}`, BACKEND_URL)

  // Forward query params
  req.nextUrl.searchParams.forEach((value, key) => {
    backendUrl.searchParams.set(key, value)
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

  const fetchOptions: RequestInit = {
    method: req.method,
    headers,
  }

  if (req.method !== "GET" && req.method !== "HEAD") {
    try {
      const body = await req.text()
      if (body) fetchOptions.body = body
    } catch {
      // No body
    }
  }

  try {
    const res = await fetch(backendUrl.toString(), fetchOptions)
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch {
    return NextResponse.json(
      { success: false, error: "Backend unavailable" },
      { status: 502 },
    )
  }
}

export const GET = proxyRequest
export const POST = proxyRequest
export const PATCH = proxyRequest
export const DELETE = proxyRequest
