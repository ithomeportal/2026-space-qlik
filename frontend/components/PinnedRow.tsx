"use client"

import { usePreferences, useReports, useToggleFavorite } from "@/lib/api"
import { ReportCard } from "./ReportCard"

export function PinnedRow() {
  const { data: prefsRes } = usePreferences()
  const { data: reportsRes } = useReports()
  const toggleFavorite = useToggleFavorite()

  const pinnedIds = prefsRes?.data?.pinned_reports ?? []
  const allReports = reportsRes?.data ?? []

  const pinnedReports = allReports.filter((r) => pinnedIds.includes(r.id))

  if (pinnedReports.length === 0) return null

  return (
    <section className="mb-10">
      <h2 className="mb-4 text-xl font-semibold text-[#1B3A5C]">Pinned</h2>
      <div className="flex gap-6 overflow-x-auto pb-2">
        {pinnedReports.slice(0, 6).map((report) => (
          <div key={report.id} className="w-[280px] shrink-0">
            <ReportCard
              report={report}
              isFavorited
              onToggleFavorite={(id) => toggleFavorite.mutate(id)}
            />
          </div>
        ))}
      </div>
    </section>
  )
}
