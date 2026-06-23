"use client"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { SessionProvider } from "next-auth/react"
import { useState, type ReactNode } from "react"
import { Toaster } from "@/components/ui/sonner"

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            retry: (failureCount, error) => {
              const msg = error instanceof Error ? error.message : ""
              // Never retry auth failures
              if (/\b401\b|\b403\b/.test(msg)) return false
              // Retry up to 5x on 5xx / network errors (covers 30–60s Render cold start)
              return failureCount < 5
            },
            retryDelay: (attemptIndex) =>
              Math.min(2000 * 2 ** attemptIndex, 30000),
          },
        },
      }),
  )

  return (
    <SessionProvider>
      <QueryClientProvider client={queryClient}>
        {children}
        {/* Light-only per project rule; richColors makes error toasts clearly red */}
        <Toaster theme="light" richColors position="top-center" />
      </QueryClientProvider>
    </SessionProvider>
  )
}
