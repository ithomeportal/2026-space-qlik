"use client"

import { useSession } from "next-auth/react"
import { redirect } from "next/navigation"
import { SearchBar } from "@/components/SearchBar"
import { PinnedRow } from "@/components/PinnedRow"
import { ReportGrid } from "@/components/ReportGrid"

export default function HomePage() {
  const { status } = useSession()

  if (status === "unauthenticated") {
    redirect("/login")
  }

  return (
    <div className="mx-auto w-full max-w-[1920px] px-4 py-6 min-[1920px]:px-12 min-[1920px]:py-8">
      {/* Search bar */}
      <div className="mb-8 flex flex-col items-center pt-4 min-[1920px]:mb-12 min-[1920px]:pt-8">
        <SearchBar />
      </div>

      {/* Pinned reports */}
      <PinnedRow />

      {/* Categorized report grid */}
      <ReportGrid />
    </div>
  )
}
