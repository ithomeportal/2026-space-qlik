"use client"

import { useState } from "react"
import { LayoutGrid, List, ExternalLink, Tag } from "lucide-react"
import { useReports, useApps, useUserTagRoles, type Report } from "@/lib/api"
import { useIsMobile } from "@/lib/use-is-mobile"
import { ReportCard, AppCard } from "./ReportCard"
import { ReportGridSkeleton } from "./skeletons/ReportGridSkeleton"

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

function TagRoleSidebar({
  activeRole,
  onSelect,
}: {
  activeRole: string | null
  onSelect: (role: string | null) => void
}) {
  const { data: rolesRes } = useUserTagRoles()
  const roles = rolesRes?.data ?? []

  if (roles.length === 0) return null

  return (
    <div className="space-y-1.5">
      <div className="mb-3 flex items-center gap-2">
        <Tag className="h-4 w-4 text-[#6B7280]" />
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
          Filters
        </h3>
      </div>
      <button
        onClick={() => onSelect(null)}
        className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors ${
          activeRole === null
            ? "bg-[#1B3A5C] text-white"
            : "text-[#374151] hover:bg-[#F3F4F6]"
        }`}
      >
        <span>All</span>
      </button>
      {roles.map((role) => (
        <button
          key={role.id}
          onClick={() => onSelect(activeRole === role.name ? null : role.name)}
          className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors ${
            activeRole === role.name
              ? "bg-[#1B3A5C] text-white"
              : "text-[#374151] hover:bg-[#F3F4F6]"
          }`}
        >
          <span className="truncate">{role.name}</span>
          <span
            className={`ml-2 shrink-0 text-xs ${
              activeRole === role.name ? "text-white/70" : "text-[#9CA3AF]"
            }`}
          >
            {role.report_count}
          </span>
        </button>
      ))}
    </div>
  )
}

export function ReportGrid() {
  const [view, setView] = useState<ViewMode>("tiles")
  const [activeRole, setActiveRole] = useState<string | null>(null)
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

  const allReports = reportsRes?.data ?? []
  const apps = appsRes?.data ?? []

  // Filter reports by selected TagRole
  const reports = activeRole
    ? allReports.filter((r) => (r.tag_roles ?? []).includes(activeRole))
    : allReports

  if (view === "list") {
    return (
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <p className="text-sm text-[#6B7280]">
            {reports.length} reports{apps.length > 0 ? ` · ${apps.length} apps` : ""}
          </p>
          <ViewToggle view={view} onChange={setView} />
        </div>

        {/* TagRole filter pills for list view */}
        <TagRoleFilterPills activeRole={activeRole} onSelect={setActiveRole} />

        {/* Apps section */}
        {apps.length > 0 && (
          <section>
            <div className="mb-3 flex items-center gap-2">
              <ExternalLink className="h-4 w-4 text-[#2563EB]" />
              <h2 className="text-lg font-semibold text-[#1B3A5C]">Apps</h2>
              <span className="text-xs text-[#9CA3AF]">{apps.length}</span>
            </div>
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
          </section>
        )}

        {/* Reports list */}
        {reports.length > 0 && (
          <section>
            <div className="mb-3 flex items-center gap-2">
              <h2 className="text-lg font-semibold text-[#1B3A5C]">Reports</h2>
              <span className="text-xs text-[#9CA3AF]">{reports.length}</span>
            </div>
            <div className="rounded-lg border border-[#E5E7EB] bg-white">
              <div className="flex items-center gap-4 border-b border-[#E5E7EB] px-4 py-2 text-xs font-medium text-[#6B7280]">
                <div className="w-10 shrink-0" />
                <div className="min-w-0 flex-1">Name</div>
                <div className="hidden min-w-0 flex-1 sm:block">Note</div>
              </div>
              <div className="divide-y divide-[#F3F4F6]">
                {reports.map((report) => (
                  <ReportCard key={report.id} report={report} view="list" />
                ))}
              </div>
            </div>
          </section>
        )}

        {reports.length === 0 && apps.length === 0 && (
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

  // Tiles view — 3-column layout
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-[#6B7280]">
          {reports.length} reports{apps.length > 0 ? ` · ${apps.length} apps` : ""}
        </p>
        <ViewToggle view={view} onChange={setView} />
      </div>

      {/* 3-column layout: TagRoles (1/5) | Reports (3/5) | Apps (1/5) */}
      <div className="flex gap-6">
        {/* Left column — TagRole filters */}
        <div className="w-1/5 shrink-0">
          <TagRoleSidebar activeRole={activeRole} onSelect={setActiveRole} />
        </div>

        {/* Center column — Reports matrix */}
        <div className="w-3/5">
          {reports.length > 0 ? (
            <div>
              <div className="mb-3 flex items-center gap-2">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-[#6B7280]">
                  Reports
                </h2>
                <span className="text-xs text-[#9CA3AF]">{reports.length}</span>
              </div>
              <div className="grid grid-cols-3 gap-6 min-[1200px]:grid-cols-4 min-[1600px]:grid-cols-5 min-[1920px]:grid-cols-6">
                {reports.map((report) => (
                  <ReportCard key={report.id} report={report} view="tiles" />
                ))}
              </div>
            </div>
          ) : (
            <div className="flex h-40 items-center justify-center text-sm text-[#6B7280]">
              {activeRole
                ? `No reports for "${activeRole}"`
                : "No reports available"}
            </div>
          )}
        </div>

        {/* Right column — Apps */}
        <div className="w-1/5 shrink-0">
          {apps.length > 0 && (
            <div>
              <div className="mb-3 flex items-center gap-2">
                <ExternalLink className="h-4 w-4 text-[#2563EB]" />
                <h2 className="text-sm font-semibold uppercase tracking-wider text-[#6B7280]">
                  Apps
                </h2>
                <span className="text-xs text-[#9CA3AF]">{apps.length}</span>
              </div>
              <div className="grid grid-cols-2 gap-4">
                {apps.map((app) => (
                  <AppCard key={app.id} app={app} view="tiles" />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {reports.length === 0 && apps.length === 0 && (
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

/** Horizontal filter pills for list view */
function TagRoleFilterPills({
  activeRole,
  onSelect,
}: {
  activeRole: string | null
  onSelect: (role: string | null) => void
}) {
  const { data: rolesRes } = useUserTagRoles()
  const roles = rolesRes?.data ?? []

  if (roles.length === 0) return null

  return (
    <div className="flex flex-wrap gap-2">
      <button
        onClick={() => onSelect(null)}
        className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
          activeRole === null
            ? "bg-[#1B3A5C] text-white"
            : "bg-[#F3F4F6] text-[#374151] hover:bg-[#E5E7EB]"
        }`}
      >
        All
      </button>
      {roles.map((role) => (
        <button
          key={role.id}
          onClick={() => onSelect(activeRole === role.name ? null : role.name)}
          className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
            activeRole === role.name
              ? "bg-[#1B3A5C] text-white"
              : "bg-[#F3F4F6] text-[#374151] hover:bg-[#E5E7EB]"
          }`}
        >
          {role.name}
          <span className="ml-1 opacity-60">{role.report_count}</span>
        </button>
      ))}
    </div>
  )
}
