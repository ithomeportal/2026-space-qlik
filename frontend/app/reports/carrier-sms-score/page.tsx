"use client"

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Download, Loader2, Search, ShieldCheck, X } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import { useDebounce } from "@/lib/use-debounce"
import {
  carrierSmsCsvHref,
  useCarrierSmsList,
  useCarrierSmsSummary,
  type CarrierSmsFilters,
  type CarrierSmsRow,
} from "@/lib/carrier-sms-api"
import { DownloadCsvButton } from "../admin-cashflow/DownloadCsvButton"
import { CarrierTable } from "./CarrierTable"
import { fmtCount, fmtDate } from "./format"

const PAGE_SIZES = [50, 100, 250]

const CSV_HEADER = [
  "Carrier", "City", "State", "DOT #", "MC #", "Active",
  "Vehicle OOS %", "Driver OOS %",
  "BASIC Unsafe", "BASIC HOS", "BASIC Fitness", "BASIC Drug/Alc", "BASIC Veh Maint",
  "MCP Risk", "MCP Risk Points", "MCP Blocked", "SMS Data Date", "MCP Last Checked",
]

function csvCell(v: string | number | boolean | null): string {
  if (v === null || v === undefined) return ""
  const s = String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function num1(v: number | null): string {
  return v === null || Number.isNaN(v) ? "" : v.toFixed(1)
}

function rowToCsvLine(r: CarrierSmsRow): string {
  return [
    r.name, r.city, r.state, r.dot_number, r.mc_number,
    r.is_active ? "Yes" : "No",
    num1(r.vehicle_oos_pct), num1(r.driver_oos_pct),
    num1(r.basic_unsafe), num1(r.basic_hos), num1(r.basic_fitness),
    num1(r.basic_drugalc), num1(r.basic_vehmaint),
    r.mcp_risk_overall, r.mcp_risk_points, r.mcp_is_blocked ? "Yes" : "",
    r.data_file_date, r.mcp_last_checked,
  ].map(csvCell).join(",")
}

function KpiCard({ label, value, tone }: { label: string; value: string; tone?: "warn" | "bad" }) {
  const color = tone === "bad" ? "text-[#B91C1C]" : tone === "warn" ? "text-[#B45309]" : "text-[#1B3A5C]"
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white px-4 py-3 shadow-sm">
      <div className="text-[11px] uppercase tracking-wider text-[#6B7280]">{label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums ${color}`}>{value}</div>
    </div>
  )
}

function CarrierSmsContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  // ---- URL state -----------------------------------------------------------
  const sort = searchParams.get("sort") || "name_asc"
  const page = Math.max(1, Number(searchParams.get("page") || "1"))
  const pageSize = PAGE_SIZES.includes(Number(searchParams.get("limit")))
    ? Number(searchParams.get("limit"))
    : 50
  const includeInactive = searchParams.get("inactive") === "1"
  const flagged = searchParams.get("flagged") === "1"
  const urlSearch = searchParams.get("q") || ""

  const [searchInput, setSearchInput] = useState(urlSearch)
  const debouncedSearch = useDebounce(searchInput, 300)

  const setParams = useCallback(
    (updates: Record<string, string | null>) => {
      const sp = new URLSearchParams(searchParams.toString())
      for (const [k, v] of Object.entries(updates)) {
        if (v === null || v === "") sp.delete(k)
        else sp.set(k, v)
      }
      router.replace(`${pathname}?${sp.toString()}`, { scroll: false })
    },
    [searchParams, router, pathname],
  )

  // Keep the URL's q param in sync with the debounced input (resets to page 1).
  const effectiveSearch = debouncedSearch.trim()
  useEffect(() => {
    if (effectiveSearch !== urlSearch) {
      setParams({ q: effectiveSearch || null, page: null })
    }
  }, [effectiveSearch, urlSearch, setParams])

  const filters: CarrierSmsFilters = useMemo(
    () => ({
      search: effectiveSearch || undefined,
      includeInactive,
      flagged,
      sort,
      page,
      limit: pageSize,
    }),
    [effectiveSearch, includeInactive, flagged, sort, page, pageSize],
  )

  const listQ = useCarrierSmsList(filters)
  const summaryQ = useCarrierSmsSummary(filters)
  const rows = useMemo(() => listQ.data?.data ?? [], [listQ.data])
  const total = listQ.data?.meta?.total ?? 0
  const summary = summaryQ.data?.data

  // ---- Selection (persists across pages) -----------------------------------
  const [selectedRows, setSelectedRows] = useState<Map<string, CarrierSmsRow>>(new Map())
  const selectedKeys = useMemo(() => new Set(selectedRows.keys()), [selectedRows])

  const toggleRow = useCallback(
    (id: string) => {
      const row = rows.find((r) => r.id === id)
      setSelectedRows((prev) => {
        const next = new Map(prev)
        if (next.has(id)) next.delete(id)
        else if (row) next.set(id, row)
        return next
      })
    },
    [rows],
  )

  const togglePage = useCallback(
    (ids: string[], allSelected: boolean) => {
      setSelectedRows((prev) => {
        const next = new Map(prev)
        if (allSelected) {
          ids.forEach((id) => next.delete(id))
        } else {
          ids.forEach((id) => {
            const row = rows.find((r) => r.id === id)
            if (row) next.set(id, row)
          })
        }
        return next
      })
    },
    [rows],
  )

  const clearSelection = () => setSelectedRows(new Map())

  const downloadSelected = () => {
    const lines = [CSV_HEADER.join(",")]
    Array.from(selectedRows.values()).forEach((r) => lines.push(rowToCsvLine(r)))
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `carrier-sms-score_selection.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-5">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <Link href="/" className="mb-1 inline-flex items-center gap-1 text-xs text-[#6B7280] hover:text-[#1B3A5C]">
            <ArrowLeft className="h-3 w-3" /> Back to portal
          </Link>
          <h1 className="flex items-center gap-2 text-xl font-semibold text-[#1B3A5C]">
            <ShieldCheck className="h-5 w-5" /> Carrier SMS Score
          </h1>
          <p className="text-xs text-[#6B7280]">
            FMCSA Safety (SMS) Out-of-Service rates, BASIC measures & final MyCarrierPortal risk per carrier.
          </p>
        </div>
        {summary && (
          <div className="text-right text-[11px] text-[#6B7280]">
            <div>SMS data as of <span className="font-medium text-[#374151]">{fmtDate(summary.sms_data_newest)}</span></div>
            <div>MCP last checked <span className="font-medium text-[#374151]">{fmtDate(summary.mcp_checked_newest)}</span></div>
          </div>
        )}
      </div>

      {/* KPI strip */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <KpiCard label="Carriers" value={summary ? fmtCount(summary.total) : "—"} />
        <KpiCard label="Above Veh Nat'l Avg" value={summary ? fmtCount(summary.above_vehicle_nat_avg) : "—"} tone="bad" />
        <KpiCard label="Above Drv Nat'l Avg" value={summary ? fmtCount(summary.above_driver_nat_avg) : "—"} tone="bad" />
        <KpiCard label="Concerning BASIC ≥75" value={summary ? fmtCount(summary.concerning_basics) : "—"} tone="warn" />
        <KpiCard label="MCP Not Acceptable" value={summary ? fmtCount(summary.mcp_not_acceptable) : "—"} tone="bad" />
      </div>

      {/* Controls */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9CA3AF]" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search carrier, DOT #, MC #, city, state…"
            className="w-full rounded-md border border-[#E5E7EB] bg-white py-1.5 pl-8 pr-8 text-sm focus:border-[#1B3A5C] focus:outline-none"
          />
          {searchInput && (
            <button
              onClick={() => setSearchInput("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[#9CA3AF] hover:text-[#374151]"
              aria-label="Clear search"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        <label className="flex items-center gap-1.5 rounded-md border border-[#E5E7EB] bg-white px-2.5 py-1.5 text-xs text-[#374151]">
          <input
            type="checkbox"
            checked={flagged}
            onChange={(e) => setParams({ flagged: e.target.checked ? "1" : null, page: null })}
            className="h-3.5 w-3.5 cursor-pointer accent-[#1B3A5C]"
          />
          Flagged only
        </label>
        <label className="flex items-center gap-1.5 rounded-md border border-[#E5E7EB] bg-white px-2.5 py-1.5 text-xs text-[#374151]">
          <input
            type="checkbox"
            checked={includeInactive}
            onChange={(e) => setParams({ inactive: e.target.checked ? "1" : null, page: null })}
            className="h-3.5 w-3.5 cursor-pointer accent-[#1B3A5C]"
          />
          Include inactive
        </label>

        <select
          value={pageSize}
          onChange={(e) => setParams({ limit: e.target.value, page: null })}
          className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs text-[#374151]"
        >
          {PAGE_SIZES.map((s) => (
            <option key={s} value={s}>{s} / page</option>
          ))}
        </select>

        <DownloadCsvButton
          href={carrierSmsCsvHref(filters)}
          label="Download all (filtered)"
          title="Download every carrier matching the current search/filter"
        />
        <button
          onClick={downloadSelected}
          disabled={selectedRows.size === 0}
          className="inline-flex items-center gap-1 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-[11px] text-[#374151] hover:bg-[#F9FAFB] hover:text-[#1B3A5C] disabled:opacity-50"
        >
          <Download className="h-3 w-3" />
          Download selected ({selectedRows.size})
        </button>
        {selectedRows.size > 0 && (
          <button
            onClick={clearSelection}
            className="text-[11px] text-[#6B7280] underline hover:text-[#374151]"
          >
            clear
          </button>
        )}
      </div>

      <div className="mb-2 text-xs text-[#6B7280]">
        {listQ.isLoading ? (
          <span className="inline-flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" /> Loading…</span>
        ) : (
          <>{fmtCount(total)} carriers{effectiveSearch ? ` matching "${effectiveSearch}"` : ""}</>
        )}
      </div>

      <CarrierTable
        rows={rows}
        total={total}
        isLoading={listQ.isLoading}
        isFetching={listQ.isFetching}
        error={listQ.error}
        sort={sort}
        page={page}
        pageSize={pageSize}
        selected={selectedKeys}
        onSortChange={(s) => setParams({ sort: s })}
        onPageChange={(p) => setParams({ page: String(p) })}
        onToggleRow={toggleRow}
        onTogglePage={togglePage}
      />
    </div>
  )
}

export default function CarrierSmsScorePage() {
  return (
    <ReportGuard reportKey="carrier-sms-score">
      <Suspense fallback={<div className="p-8 text-center text-[#6B7280]"><Loader2 className="mx-auto h-5 w-5 animate-spin" /></div>}>
        <CarrierSmsContent />
      </Suspense>
    </ReportGuard>
  )
}
