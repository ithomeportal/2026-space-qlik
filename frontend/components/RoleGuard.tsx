"use client"

import { useSession } from "next-auth/react"
import { redirect } from "next/navigation"
import type { ReactNode } from "react"

interface RoleGuardProps {
  roles: string[]
  children: ReactNode
  fallback?: ReactNode
}

export function RoleGuard({ roles, children, fallback }: RoleGuardProps) {
  const { data: session, status } = useSession()

  if (status === "loading") {
    return <div className="flex h-full items-center justify-center p-8">Loading...</div>
  }

  if (!session?.user) {
    redirect("/login")
  }

  const userRolesLower = (session.user.roles ?? []).map((r) => r.toLowerCase())
  const allowedLower = roles.map((r) => r.toLowerCase())
  const hasAccess =
    userRolesLower.includes("admin") ||
    allowedLower.some((r) => userRolesLower.includes(r))

  if (!hasAccess) {
    return (
      fallback ?? (
        <div className="flex min-h-[calc(100vh-64px)] flex-col items-center justify-center bg-[#F9FAFB] p-8">
          <div className="max-w-md rounded-xl border border-[#E5E7EB] bg-white p-8 text-center shadow-sm">
            <h2 className="text-xl font-semibold text-[#1B3A5C]">Access Denied</h2>
            <p className="mt-2 text-sm text-[#6B7280]">
              You don&apos;t have permission to view this report. Required role:{" "}
              <span className="font-medium text-[#374151]">
                {roles.join(", ")}
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
