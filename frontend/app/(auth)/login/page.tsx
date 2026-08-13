"use client"

import { useSession } from "next-auth/react"
import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { isOrgEmail } from "@/lib/allowed-domains"

export default function LoginPage() {
  const { status } = useSession()
  const [email, setEmail] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (status === "authenticated") {
      window.location.href = "/"
    }
  }, [status])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")

    // UX only — lib/auth.ts is authoritative and runs server-side before any
    // token is generated or mailed. Kept in sync via the shared domain list so
    // the two cannot drift into disagreeing about who may sign in.
    if (!isOrgEmail(email)) {
      setError("Only UNILINK company email addresses are allowed")
      return
    }

    setLoading(true)
    try {
      // Was signIn("resend", …), whose sendVerificationRequest wrote the code
      // to Postgres with Prisma. Issuing now happens in the FastAPI backend so
      // this app never holds DATABASE_URL (see lib/auth-backend.ts).
      const res = await fetch("/api/auth/send-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => null)
        setError(data?.error || "Failed to send verification code. Please try again.")
        setLoading(false)
        return
      }

      // Redirect to verify page with email in query params
      window.location.href = `/login/verify?email=${encodeURIComponent(email)}`
    } catch {
      setError("Failed to send verification code")
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F9FAFB] px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-[#1B3A5C]">
            <span className="text-lg font-bold text-[#D02228]">US</span>
          </div>
          <CardTitle className="text-2xl font-bold text-[#1B3A5C]">
            UNILINK Space
          </CardTitle>
          <CardDescription>
            Sign in with your corporate email to access dashboards
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              type="email"
              placeholder="your email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
            {error && (
              <p className="text-sm text-red-600">{error}</p>
            )}
            <Button
              type="submit"
              className="w-full bg-[#2563EB] hover:bg-[#1D4ED8]"
              disabled={loading}
            >
              {loading ? "Sending code..." : "Send verification code"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
