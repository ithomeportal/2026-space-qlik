"use client"

import { Suspense, useState, useRef, useEffect } from "react"
import { useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

function VerifyForm() {
  const searchParams = useSearchParams()
  const email = searchParams.get("email") || ""
  const [code, setCode] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")

    if (code.length !== 8) {
      setError("Please enter the 8-digit code")
      return
    }

    setLoading(true)
    try {
      const res = await fetch("/api/auth/verify-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code }),
      })

      const data = await res.json()

      if (data.url) {
        window.location.href = data.url
      } else {
        setError(data.error || "Invalid code. Please try again.")
        setLoading(false)
      }
    } catch {
      setError("Verification failed. Please try again.")
      setLoading(false)
    }
  }

  return (
    <Card className="w-full max-w-md text-center">
      <CardHeader>
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-[#2563EB]">
          <svg
            className="h-6 w-6 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
            />
          </svg>
        </div>
        <CardTitle className="text-2xl font-bold text-[#1B3A5C]">
          Check your email
        </CardTitle>
        <CardDescription>
          We sent an 8-digit code to{" "}
          {email ? <strong>{email}</strong> : "your email"}.
          Enter it below to sign in.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            ref={inputRef}
            type="text"
            inputMode="numeric"
            maxLength={8}
            placeholder="Enter 8-digit code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 8))}
            className="text-center text-2xl font-mono tracking-[0.3em] h-14"
            autoComplete="one-time-code"
          />
          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}
          <Button
            type="submit"
            className="w-full bg-[#2563EB] hover:bg-[#1D4ED8]"
            disabled={loading || code.length !== 8}
          >
            {loading ? "Verifying..." : "Verify code"}
          </Button>
        </form>
        <p className="mt-4 text-sm text-[#6B7280]">
          Code expires in 10 minutes. Check your spam folder if you don&apos;t see it.
        </p>
      </CardContent>
    </Card>
  )
}

export default function VerifyPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F9FAFB] px-4">
      <Suspense fallback={
        <Card className="w-full max-w-md text-center p-8">
          <p className="text-[#6B7280]">Loading...</p>
        </Card>
      }>
        <VerifyForm />
      </Suspense>
    </div>
  )
}
