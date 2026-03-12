"use client"

import { signIn } from "next-auth/react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"

export default function LoginPage() {
  const [email, setEmail] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")

    if (!email.endsWith("@unilinktransportation.com")) {
      setError("Only @unilinktransportation.com emails are allowed")
      return
    }

    setLoading(true)
    try {
      const res = await signIn("resend", {
        email,
        redirect: false,
      })

      if (res?.error) {
        setError("Failed to send verification code. Please try again.")
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
            <span className="text-lg font-bold text-white">AH</span>
          </div>
          <CardTitle className="text-2xl font-bold text-[#1B3A5C]">
            Analytics Hub
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
