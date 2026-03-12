"use client"

import { useReports, usePreferences, useToggleFavorite, type Report } from "@/lib/api"
import { ReportCard } from "./ReportCard"
import { ReportGridSkeleton } from "./skeletons/ReportGridSkeleton"

export function ReportGrid() {
  const { data: reportsRes, isLoading } = useReports()
  const { data: prefsRes } = usePreferences()
  const toggleFavorite = useToggleFavorite()

  if (isLoading) return <ReportGridSkeleton />

  const reports = reportsRes?.data ?? []
  const pinnedIds = prefsRes?.data?.pinned_reports ?? []

  // Group reports by category
  const grouped = reports.reduce<Record<string, Report[]>>((acc, report) => {
    const cat = report.category ?? "Other"
    return { ...acc, [cat]: [...(acc[cat] ?? []), report] }
  }, {})

  const categoryOrder = ["Executive", "Finance", "Operations", "Sales", "HR", "IT"]
  const sortedCategories = Object.keys(grouped).sort(
    (a, b) => (categoryOrder.indexOf(a) === -1 ? 99 : categoryOrder.indexOf(a)) -
              (categoryOrder.indexOf(b) === -1 ? 99 : categoryOrder.indexOf(b)),
  )

  return (
    <div className="space-y-10">
      {sortedCategories.map((category) => (
        <section key={category}>
          <h2 className="mb-4 text-xl font-semibold text-[#1B3A5C]">{category}</h2>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {grouped[category].map((report) => (
              <ReportCard
                key={report.id}
                report={report}
                isFavorited={pinnedIds.includes(report.id)}
                onToggleFavorite={(id) => toggleFavorite.mutate(id)}
              />
            ))}
          </div>
        </section>
      ))}

      {reports.length === 0 && !isLoading && (
        <div className="py-16 text-center text-[#6B7280]">
          <p className="text-lg">No reports available</p>
          <p className="mt-1 text-sm">Contact your admin to get access to reports.</p>
        </div>
      )}
    </div>
  )
}
