import { NextRequest, NextResponse } from "next/server"

import { issueLoginCode } from "@/lib/auth-backend"
import { isOrgEmail } from "@/lib/allowed-domains"

// Replaces `signIn("resend", …)` as the "send me a code" step. The old flow used
// NextAuth's Email provider, whose `sendVerificationRequest` wrote the code to
// Postgres with Prisma; issuing now happens in the backend so this process never
// touches the database. See lib/auth-backend.ts.

export async function POST(request: NextRequest) {
  let email: unknown
  let callbackUrl: unknown
  try {
    const body = await request.json()
    email = body?.email
    callbackUrl = body?.callbackUrl
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 })
  }

  if (typeof email !== "string" || !email.trim()) {
    return NextResponse.json({ error: "Email is required" }, { status: 400 })
  }

  const normalised = email.trim().toLowerCase()

  // The backend enforces this too (it is the authority, and it logs the domain
  // only). Checking here as well avoids a pointless round-trip and keeps the
  // rejection message identical to the client-side pre-check.
  if (!isOrgEmail(normalised)) {
    return NextResponse.json(
      { error: "Only UNILINK company email addresses are allowed" },
      { status: 403 },
    )
  }

  const res = await issueLoginCode(
    normalised,
    typeof callbackUrl === "string" && callbackUrl ? callbackUrl : "/",
  )

  if (!res.ok) {
    // Never surface the backend's own message: it can carry provider detail.
    // 403 is the only status worth passing through, since it is actionable.
    const status = res.status === 403 ? 403 : 502
    console.error(`[auth] issue code failed (status ${res.status})`)
    return NextResponse.json(
      {
        error:
          status === 403
            ? "Only UNILINK company email addresses are allowed"
            : "Could not send the verification code. Please try again.",
      },
      { status },
    )
  }

  // Deliberately does NOT echo the code or whether the address already had a
  // user row — that would be an account-enumeration oracle.
  return NextResponse.json({ sent: true })
}
