"use client"

import { signOut, useSession } from "next-auth/react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import Link from "next/link"

export function Header() {
  const { data: session } = useSession()

  return (
    <header className="sticky top-0 z-50 h-16 border-b border-[#E5E7EB] bg-white">
      <div className="mx-auto flex h-full max-w-[1280px] items-center justify-between px-6 md:px-12">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#1B3A5C]">
            <span className="text-sm font-bold text-white">US</span>
          </div>
          <span className="hidden text-lg font-semibold text-[#1B3A5C] sm:inline">
            UNILINK Space
          </span>
        </Link>

        {/* Right side */}
        <div className="flex items-center gap-3">
          {session?.user && (
            <DropdownMenu>
              <DropdownMenuTrigger>
                <Button variant="ghost" className="flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#2563EB] text-sm font-medium text-white">
                    {session.user.name
                      ?.split(" ")
                      .map((n) => n[0])
                      .join("")
                      .slice(0, 2)
                      .toUpperCase() ?? "U"}
                  </div>
                  <span className="hidden text-sm text-[#111827] md:inline">
                    {session.user.name}
                  </span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <div className="px-2 py-1.5">
                  <p className="text-sm font-medium">{session.user.name}</p>
                  <p className="text-xs text-[#6B7280]">{session.user.email}</p>
                </div>
                <DropdownMenuSeparator />
                {session.user.roles?.includes("admin") && (
                  <DropdownMenuItem>
                    <Link href="/admin">Admin Console</Link>
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem
                  onClick={() => signOut({ callbackUrl: "/login" })}
                >
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>
    </header>
  )
}
