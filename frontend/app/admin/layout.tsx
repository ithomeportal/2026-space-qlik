"use client"

import { RoleGuard } from "@/components/RoleGuard"
import Link from "next/link"
import { usePathname } from "next/navigation"
import type { ReactNode } from "react"

const NAV_ITEMS = [
  { href: "/admin", label: "Dashboard" },
  { href: "/admin/reports", label: "Reports" },
  { href: "/admin/apps", label: "Apps" },
  { href: "/admin/roles", label: "Tag Roles" },
  { href: "/admin/users", label: "Users" },
]

export default function AdminLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname()

  return (
    <RoleGuard roles={["admin"]}>
      <div className="flex min-h-[calc(100vh-64px)]">
        {/* Sidebar */}
        <aside className="w-56 shrink-0 border-r border-[#E5E7EB] bg-[#F9FAFB] p-4">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-[#6B7280]">
            Admin Console
          </h2>
          <nav className="space-y-1">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`block rounded-lg px-3 py-2 text-sm transition-colors ${
                  pathname === item.href
                    ? "bg-[#2563EB] text-white"
                    : "text-[#111827] hover:bg-[#E5E7EB]"
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </aside>

        {/* Content */}
        <div className="flex-1 p-8">{children}</div>
      </div>
    </RoleGuard>
  )
}
