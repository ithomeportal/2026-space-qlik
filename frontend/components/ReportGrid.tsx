"use client"

import { useState } from "react"
import { LayoutGrid, List } from "lucide-react"
import { useReports, usePreferences, useToggleFavorite, type Report } from "@/lib/api"
import { useIsMobile } from "@/lib/use-is-mobile"
import { ReportCard } from "./ReportCard"
import { ReportGridSkeleton } from "./skeletons/ReportGridSkeleton"
import { CATEGORY_COLORS } from "./ReportIcons"

type ViewMode = "tiles" | "list"

function ViewToggle({ view, onChange }: { view: ViewMode; onChange: (v: ViewMode) => void }) {
  return (
    <div className="flex items-center gap-1 rounded-lg border border-[#E5E7EB] bg-white p-1">
      <button
        onClick={() => onChange("tiles")}
        className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
          view === "tiles"
            ? "bg-[#1B3A5C] text-white"
            : "text-[#6B7280] hover:bg-[#F3F4F6]"
        }`}
      >
        <LayoutGrid className="h-3.5 w-3.5" />
        Tiles
      </button>
      <button
        onClick={() => onChange("list")}
        className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
          view === "list"
            ? "bg-[#1B3A5C] text-white"
            : "text-[#6B7280] hover:bg-[#F3F4F6]"
        }`}
      >
        <List className="h-3.5 w-3.5" />
        List
      </button>
    </div>
  )
}

export function ReportGrid() {
  const [view, setView] = useState<ViewMode>("tiles")
  const isMobile = useIsMobile()
  const { data: reportsRes, isLoading } = useReports(undefined, isMobile)
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
    (a, b) =>
      (categoryOrder.indexOf(a) === -1 ? 99 : categoryOrder.indexOf(a)) -
      (categoryOrder.indexOf(b) === -1 ? 99 : categoryOrder.indexOf(b)),
  )

  return (
    <div className="space-y-8">
      {/* View toggle */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-[#6B7280]">{reports.length} reports</p>
        <ViewToggle view={view} onChange={setView} />
      </div>

      {/* Categories */}
      {sortedCategories.map((category) => (
        <section key={category}>
          <div className="mb-4 flex items-center gap-2">
            <div
              className={`h-2 w-2 rounded-full ${CATEGORY_COLORS[category] ?? "bg-gray-400"}`}
            />
            <h2 className="text-lg font-semibold text-[#1B3A5C]">{category}</h2>
            <span className="text-xs text-[#9CA3AF]">
              {grouped[category].length}
            </span>
          </div>

          {view === "tiles" ? (
            /* Tile grid — like iPad app icons */
            <div className="flex flex-wrap gap-8">
              {grouped[category].map((report) => (
                <ReportCard
                  key={report.id}
                  report={report}
                  view="tiles"
                  isFavorited={pinnedIds.includes(report.id)}
                  onToggleFavorite={(id) => toggleFavorite.mutate(id)}
                />
              ))}
            </div>
          ) : (
            /* List view — like OneDrive */
            <div className="rounded-lg border border-[#E5E7EB] bg-white">
              {/* List header */}
              <div className="flex items-center gap-4 border-b border-[#E5E7EB] px-4 py-2 text-xs font-medium text-[#6B7280]">
                <div className="w-10 shrink-0" />
                <div className="min-w-0 flex-1">Name</div>
                <div className="hidden w-28 shrink-0 sm:block">Category</div>
                <div className="hidden w-24 shrink-0 md:block">Owner</div>
                <div className="hidden w-24 shrink-0 text-right lg:block">Updated</div>
                <div className="w-6 shrink-0" />
              </div>
              {/* List rows */}
              <div className="divide-y divide-[#F3F4F6]">
                {grouped[category].map((report) => (
                  <ReportCard
                    key={report.id}
                    report={report}
                    view="list"
                    isFavorited={pinnedIds.includes(report.id)}
                    onToggleFavorite={(id) => toggleFavorite.mutate(id)}
                  />
                ))}
              </div>
            </div>
          )}
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
