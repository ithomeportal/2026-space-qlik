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

  const userRoles = session.user.roles ?? []
  const hasAccess = roles.some((role) => userRoles.includes(role))

  if (!hasAccess) {
    return (
      fallback ?? (
        <div className="flex h-full flex-col items-center justify-center p-8">
          <h2 className="text-xl font-semibold text-[#1B3A5C]">Access Denied</h2>
          <p className="mt-2 text-[#6B7280]">
            You don&apos;t have permission to view this page.
          </p>
        </div>
      )
    )
  }

  return <>{children}</>
}
