"use client"

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"

export default function VerifyPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F9FAFB] px-4">
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
            We sent a verification code to your email. Enter the code from the
            email to sign in.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-[#6B7280]">
            The code expires in 10 minutes. Check your spam folder if you don&apos;t
            see it.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
