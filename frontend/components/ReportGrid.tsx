"use client"

import { useState } from "react"
import { LayoutGrid, List, ExternalLink } from "lucide-react"
import { useReports, useApps, type Report } from "@/lib/api"
import { useIsMobile } from "@/lib/use-is-mobile"
import { ReportCard, AppCard } from "./ReportCard"
import { ReportGridSkeleton } from "./skeletons/ReportGridSkeleton"
import { CATEGORY_COLORS } from "./ReportIcons"

type ViewMode = "tiles" | "list"

function ViewToggle({
  view,
  onChange,
}: {
  view: ViewMode
  onChange: (v: ViewMode) => void
}) {
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
  const { data: reportsRes, isLoading, isError, refetch } = useReports(undefined, isMobile)
  const { data: appsRes } = useApps()

  if (isLoading) return <ReportGridSkeleton />

  if (isError) {
    return (
      <div className="py-16 text-center">
        <p className="text-lg font-medium text-[#1B3A5C]">
          Loading reports...
        </p>
        <p className="mt-2 text-sm text-[#6B7280]">
          The server is waking up. This may take up to 30 seconds on first load.
        </p>
        <button
          onClick={() => refetch()}
          className="mt-4 rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1D4ED8]"
        >
          Retry now
        </button>
      </div>
    )
  }

  const reports = reportsRes?.data ?? []
  const apps = appsRes?.data ?? []

  // Group reports by category
  const grouped = reports.reduce<Record<string, Report[]>>((acc, report) => {
    const cat = report.category ?? "Other"
    return { ...acc, [cat]: [...(acc[cat] ?? []), report] }
  }, {})

  const categoryOrder = [
    "Executive",
    "Finance",
    "Operations",
    "Sales",
    "HR",
    "IT",
  ]
  const sortedCategories = Object.keys(grouped).sort(
    (a, b) =>
      (categoryOrder.indexOf(a) === -1 ? 99 : categoryOrder.indexOf(a)) -
      (categoryOrder.indexOf(b) === -1 ? 99 : categoryOrder.indexOf(b))
  )

  return (
    <div className="space-y-8">
      {/* View toggle */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-[#6B7280]">
          {reports.length} reports{apps.length > 0 ? ` · ${apps.length} apps` : ""}
        </p>
        <ViewToggle view={view} onChange={setView} />
      </div>

      {/* Apps section */}
      {apps.length > 0 && (
        <section>
          <div className="mb-4 flex items-center gap-2">
            <ExternalLink className="h-4 w-4 text-[#2563EB]" />
            <h2 className="text-lg font-semibold text-[#1B3A5C]">Apps</h2>
            <span className="text-xs text-[#9CA3AF]">{apps.length}</span>
          </div>

          {view === "tiles" ? (
            <div className="flex flex-wrap gap-8">
              {apps.map((app) => (
                <AppCard key={app.id} app={app} view="tiles" />
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-[#E5E7EB] bg-white">
              <div className="flex items-center gap-4 border-b border-[#E5E7EB] px-4 py-2 text-xs font-medium text-[#6B7280]">
                <div className="w-10 shrink-0" />
                <div className="min-w-0 flex-1">Name</div>
                <div className="w-16 shrink-0">Type</div>
              </div>
              <div className="divide-y divide-[#F3F4F6]">
                {apps.map((app) => (
                  <AppCard key={app.id} app={app} view="list" />
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Report categories */}
      {sortedCategories.map((category) => (
        <section key={category}>
          <div className="mb-4 flex items-center gap-2">
            <div
              className={`h-2 w-2 rounded-full ${CATEGORY_COLORS[category] ?? "bg-gray-400"}`}
            />
            <h2 className="text-lg font-semibold text-[#1B3A5C]">
              {category}
            </h2>
            <span className="text-xs text-[#9CA3AF]">
              {grouped[category].length}
            </span>
          </div>

          {view === "tiles" ? (
            <div className="flex flex-wrap gap-8">
              {grouped[category].map((report) => (
                <ReportCard key={report.id} report={report} view="tiles" />
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-[#E5E7EB] bg-white">
              <div className="flex items-center gap-4 border-b border-[#E5E7EB] px-4 py-2 text-xs font-medium text-[#6B7280]">
                <div className="w-10 shrink-0" />
                <div className="min-w-0 flex-1">Name</div>
                <div className="hidden w-28 shrink-0 sm:block">Category</div>
                <div className="hidden w-24 shrink-0 md:block">Owner</div>
                <div className="hidden w-24 shrink-0 text-right lg:block">
                  Updated
                </div>
              </div>
              <div className="divide-y divide-[#F3F4F6]">
                {grouped[category].map((report) => (
                  <ReportCard key={report.id} report={report} view="list" />
                ))}
              </div>
            </div>
          )}
        </section>
      ))}

      {reports.length === 0 && apps.length === 0 && !isLoading && (
        <div className="py-16 text-center text-[#6B7280]">
          <p className="text-lg">No reports or apps available</p>
          <p className="mt-1 text-sm">
            Contact your admin to get access to reports.
          </p>
        </div>
      )}
    </div>
  )
}
