import { NextRequest, NextResponse } from "next/server"
import { prisma } from "@/lib/db"

function generateCode(token: string): string {
  let hash = 0
  for (let i = 0; i < token.length; i++) {
    const char = token.charCodeAt(i)
    hash = ((hash << 5) - hash + char) | 0
  }
  return String(Math.abs(hash) % 100000000).padStart(8, "0")
}

export async function POST(request: NextRequest) {
  const { email, code } = await request.json()

  if (!email || !code) {
    return NextResponse.json({ error: "Email and code are required" }, { status: 400 })
  }

  // Find the verification token for this email
  const tokens = await prisma.verificationToken.findMany({
    where: {
      identifier: email,
      expires: { gt: new Date() },
    },
  })

  // Check if any token matches the code
  for (const record of tokens) {
    const expectedCode = generateCode(record.token)
    if (expectedCode === code) {
      // Build the NextAuth callback URL
      const baseUrl = process.env.NEXTAUTH_URL || `https://${request.headers.get("host")}`
      const callbackUrl = `${baseUrl}/api/auth/callback/email?token=${encodeURIComponent(record.token)}&email=${encodeURIComponent(email)}`

      return NextResponse.json({ url: callbackUrl })
    }
  }

  return NextResponse.json({ error: "Invalid or expired code" }, { status: 401 })
}
