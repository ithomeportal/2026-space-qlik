"use client"

import { useQuery } from "@tanstack/react-query"
import { useSession } from "next-auth/react"
import { redirect } from "next/navigation"
import type { ReactNode } from "react"

interface ReportGuardProps {
  reportKey: string
  children: ReactNode
  fallback?: ReactNode
}

interface AccessResponse {
  success: boolean
  data?: { key: string; allowed: boolean; roles: string[] }
}

/**
 * DB-backed access gate for code-made reports.
 *
 * Calls `GET /api/proxy/reports/access/<reportKey>` and renders the
 * Access Denied banner driven by the live role list managed via
 * `/admin/reports`. Cache is keyed by reportKey so the answer is reused
 * across re-renders and across reports rendered in the same session.
 *
 * Replaces the older `<RoleGuard roles={[...REPORT_ACCESS["X"]]}>`
 * pattern which read from a hard-coded constant in
 * `frontend/lib/report-access.ts`. The DB is now the single source of truth.
 */
export function ReportGuard({ reportKey, children, fallback }: ReportGuardProps) {
  const { data: session, status: authStatus } = useSession()
  const accessQ = useQuery({
    queryKey: ["report-access", reportKey],
    queryFn: async (): Promise<AccessResponse> => {
      const res = await fetch(
        `/api/proxy/reports/access/${encodeURIComponent(reportKey)}`,
        { headers: { "Content-Type": "application/json" } },
      )
      if (!res.ok) throw new Error(`access lookup failed: ${res.status}`)
      return res.json()
    },
    enabled: authStatus === "authenticated",
    staleTime: 60 * 1000,
  })

  if (authStatus === "loading" || (authStatus === "authenticated" && accessQ.isLoading)) {
    return <div className="flex h-full items-center justify-center p-8">Loading...</div>
  }
  if (authStatus !== "authenticated" || !session?.user) {
    redirect("/login")
  }

  const data = accessQ.data?.data
  const allowed = !!data?.allowed
  const roles = data?.roles ?? []

  if (!allowed) {
    return (
      fallback ?? (
        <div className="flex min-h-[calc(100vh-64px)] flex-col items-center justify-center bg-[#F9FAFB] p-8">
          <div className="max-w-md rounded-xl border border-[#E5E7EB] bg-white p-8 text-center shadow-sm">
            <h2 className="text-xl font-semibold text-[#1B3A5C]">Access Denied</h2>
            <p className="mt-2 text-sm text-[#6B7280]">
              You don&apos;t have permission to view this report. Required role:{" "}
              <span className="font-medium text-[#374151]">
                {roles.length ? roles.join(", ") : "(no roles assigned)"}
              </span>
              .
            </p>
            <p className="mt-3 text-xs text-[#9CA3AF]">
              Ask an admin to assign you one of these TagRoles, then reload the page.
            </p>
          </div>
        </div>
      )
    )
  }

  return <>{children}</>
}
