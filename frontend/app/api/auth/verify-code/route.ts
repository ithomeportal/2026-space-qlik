import { NextRequest, NextResponse } from "next/server"
import { prisma } from "@/lib/db"

export async function POST(request: NextRequest) {
  const { email, code } = await request.json()

  if (!email || !code) {
    return NextResponse.json({ error: "Email and code are required" }, { status: 400 })
  }

  // Look up the code → callback URL mapping
  const record = await prisma.emailCode.findUnique({
    where: {
      email_code: { email, code },
    },
  })

  if (!record || record.expires < new Date()) {
    return NextResponse.json({ error: "Invalid or expired code" }, { status: 401 })
  }

  // Clean up used code
  await prisma.emailCode.delete({ where: { id: record.id } })

  return NextResponse.json({ url: record.callbackUrl })
}
