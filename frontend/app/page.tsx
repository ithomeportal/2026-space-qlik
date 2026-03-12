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
    <div className="mx-auto max-w-[1280px] px-6 py-8 md:px-12">
      {/* Search-first hero */}
      <div className="mb-12 flex flex-col items-center pt-8">
        <h1 className="mb-6 text-center text-3xl font-bold text-[#1B3A5C] md:text-4xl">
          Find the data you need
        </h1>
        <SearchBar />
      </div>

      {/* Pinned reports */}
      <PinnedRow />

      {/* Categorized report grid */}
      <ReportGrid />
    </div>
  )
}
