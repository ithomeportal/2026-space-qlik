"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { ArrowLeft, ExternalLink, Library, Loader2, Search, Users } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import {
  REPORT_OVERLAY,
  useReportsCatalog,
  type CatalogReport,
} from "@/lib/reports-index-api"

export default function ReportsIndexPage() {
  return (
    <ReportGuard reportKey="reports-index">
      <ReportsIndexContent />
    </ReportGuard>
  )
}

function ReportsIndexContent() {
  const { data, isLoading, isError } = useReportsCatalog()
  const [query, setQuery] = useState("")

  const reports = useMemo(() => data?.data ?? [], [data])

  // key -> {title, path} so related links resolve to live titles/paths.
  const byKey = useMemo(() => {
    const m = new Map<string, CatalogReport>()
    for (const r of reports) m.set(r.key, r)
    return m
  }, [reports])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return reports
    return reports.filter((r) => {
      const hay = [
        r.title,
        r.description ?? "",
        r.note ?? "",
        r.category ?? "",
        r.tag_roles.join(" "),
        r.tags.join(" "),
        REPORT_OVERLAY[r.key]?.kpis ?? "",
      ]
        .join(" ")
        .toLowerCase()
      return hay.includes(q)
    })
  }, [reports, query])

  // Group by category for a scannable directory.
  const groups = useMemo(() => {
    const g = new Map<string, CatalogReport[]>()
    for (const r of filtered) {
      const cat = r.category || "Other"
      if (!g.has(cat)) g.set(cat, [])
      g.get(cat)!.push(r)
    }
    return Array.from(g.entries()).sort((a, b) => a[0].localeCompare(b[0]))
  }, [filtered])

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Top bar */}
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link
          href="/"
          className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <div className="flex items-center gap-2">
          <Library className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">Reports Index</h1>
          <span className="rounded-full bg-[#EEF2FF] px-2 py-0.5 text-xs text-[#3730A3]">
            Directors &amp; Managers
          </span>
        </div>
        <div className="ml-auto text-xs text-[#6B7280]">
          {reports.length} report{reports.length === 1 ? "" : "s"}
        </div>
      </div>

      {/* Search */}
      <div className="border-b border-[#E5E7EB] bg-white px-4 py-3">
        <div className="relative mx-auto w-full max-w-[1100px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9CA3AF]" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by name, KPI, audience, or keyword…"
            className="w-full rounded-lg border border-[#E5E7EB] bg-white py-2 pl-9 pr-3 text-sm text-[#111827] outline-none placeholder:text-[#9CA3AF] focus:border-[#1B3A5C]"
          />
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1100px] flex-1 px-4 py-6">
        {isLoading && (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-[#6B7280]">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading catalog…
          </div>
        )}

        {isError && (
          <div className="rounded-lg border border-[#FECACA] bg-[#FEF2F2] p-4 text-sm text-[#991B1B]">
            Could not load the report catalog. The backend may be waking up — try
            again in a moment.
          </div>
        )}

        {!isLoading && !isError && filtered.length === 0 && (
          <div className="py-16 text-center text-sm text-[#6B7280]">
            No reports match “{query}”.
          </div>
        )}

        {!isLoading &&
          !isError &&
          groups.map(([category, rows]) => (
            <section key={category} className="mb-8">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#9CA3AF]">
                {category}
              </h2>
              <div className="overflow-hidden rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-[#E5E7EB] bg-[#F9FAFB] text-xs font-medium text-[#6B7280]">
                      <th className="w-[22%] px-4 py-2">Report</th>
                      <th className="px-4 py-2">Summary · KPIs · Audience</th>
                      <th className="w-[22%] px-4 py-2">Links</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <ReportRow key={r.key} report={r} byKey={byKey} />
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
      </div>
    </div>
  )
}

function ReportRow({
  report,
  byKey,
}: {
  report: CatalogReport
  byKey: Map<string, CatalogReport>
}) {
  const overlay = REPORT_OVERLAY[report.key]
  const related = (overlay?.related ?? [])
    .map((k) => byKey.get(k))
    .filter((r): r is CatalogReport => Boolean(r))

  return (
    <tr className="border-b border-[#F3F4F6] align-top last:border-b-0 hover:bg-[#FAFBFC]">
      {/* Col 1 — name */}
      <td className="px-4 py-3">
        <Link
          href={report.custom_path}
          className="text-sm font-semibold text-[#1B3A5C] hover:underline"
        >
          {report.title}
        </Link>
      </td>

      {/* Col 2 — summary + KPIs + audience */}
      <td className="px-4 py-3">
        {report.description && (
          <p className="text-sm text-[#374151]">{report.description}</p>
        )}
        {overlay?.kpis && (
          <p className="mt-1 text-xs text-[#6B7280]">
            <span className="font-medium text-[#374151]">KPIs:</span>{" "}
            {overlay.kpis}
          </p>
        )}
        {report.tag_roles.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1">
            <Users className="h-3 w-3 text-[#9CA3AF]" />
            {report.tag_roles.map((role) => (
              <span
                key={role}
                className="rounded-full bg-[#EEF2FF] px-2 py-0.5 text-[11px] text-[#3730A3]"
              >
                {role}
              </span>
            ))}
          </div>
        )}
      </td>

      {/* Col 3 — links */}
      <td className="px-4 py-3">
        <Link
          href={report.custom_path}
          className="inline-flex items-center gap-1 text-sm font-medium text-[#1B3A5C] hover:underline"
        >
          Open report
          <ExternalLink className="h-3 w-3" />
        </Link>
        {related.length > 0 && (
          <div className="mt-2">
            <p className="text-[11px] font-medium uppercase tracking-wide text-[#9CA3AF]">
              Related
            </p>
            <ul className="mt-1 space-y-0.5">
              {related.map((rel) => (
                <li key={rel.key}>
                  <Link
                    href={rel.custom_path}
                    className="text-xs text-[#6B7280] hover:text-[#1B3A5C] hover:underline"
                  >
                    {rel.title}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </td>
    </tr>
  )
}
