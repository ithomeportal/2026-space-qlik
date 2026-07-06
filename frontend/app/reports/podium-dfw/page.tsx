"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { ArrowLeft, Loader2, Search, Trophy, X } from "lucide-react"
import { useSortable, SortableTh } from "@/components/SortableTable"
import {
  usePodiumOverview,
  fmtCurrency,
  fmtInt,
  fmtPct,
  fmtDateTime,
  type PodiumRange,
  type PodiumRow,
} from "@/lib/podium-dfw-api"
import { ReportGuard } from "@/components/ReportGuard"
const RANGE_OPTIONS: { key: PodiumRange; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "wtd", label: "Week to date" },
  { key: "mtd", label: "Month to date" },
]

type TeamFilter = "all" | "TM1" | "TM2" | "TM3" | "TM4"

const TEAM_OPTIONS: { key: TeamFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "TM1", label: "TM1" },
  { key: "TM2", label: "TM2" },
  { key: "TM3", label: "TM3" },
  { key: "TM4", label: "TM4" },
]

function normalizeTeam(v: string | null | undefined): string {
  return (v ?? "").trim().toUpperCase()
}

// ---------------------------------------------------------------------------
// Text filters (before the KPI cards) — case-insensitive contains match.
// ---------------------------------------------------------------------------
type TextFilters = {
  customer: string
  order: string
  origin: string
  destination: string
  carrier: string
  postedBy: string
  contractType: string
  equipmentType: string
}

const EMPTY_FILTERS: TextFilters = {
  customer: "",
  order: "",
  origin: "",
  destination: "",
  carrier: "",
  postedBy: "",
  contractType: "",
  equipmentType: "",
}

const FILTER_FIELDS: { key: keyof TextFilters; label: string; placeholder: string }[] = [
  { key: "customer",     label: "Customer",      placeholder: "Search customer…" },
  { key: "order",        label: "Order",         placeholder: "Search #order…" },
  { key: "origin",       label: "Origin",        placeholder: "Search origin…" },
  { key: "destination",  label: "Destination",   placeholder: "Search destination…" },
  { key: "carrier",      label: "Carrier",       placeholder: "Search carrier…" },
  { key: "postedBy",     label: "Posted by",     placeholder: "Search posted by…" },
  { key: "contractType", label: "Contract Type", placeholder: "Search contract type…" },
  { key: "equipmentType", label: "Equipment Type", placeholder: "Search equipment…" },
]

function containsCi(value: string | null | undefined, needle: string): boolean {
  if (!needle) return true
  return (value ?? "").toLowerCase().includes(needle)
}

export default function PodiumDfwPage() {
  return (
    <ReportGuard reportKey="podium-dfw">
      <PodiumDfwContent />
    </ReportGuard>
  )
}

function PodiumDfwContent() {
  const [range, setRange] = useState<PodiumRange>("today")
  const [teamFilter, setTeamFilter] = useState<TeamFilter>("all")
  const [filters, setFilters] = useState<TextFilters>(EMPTY_FILTERS)
  const q = usePodiumOverview(range)

  const rawRows = q.data?.data?.rows ?? []

  // Filter rows by team (client-side — datalake already returns all DFW rows).
  const teamRows = useMemo(() => {
    if (teamFilter === "all") return rawRows
    const target = teamFilter.toUpperCase()
    return rawRows.filter((r) => normalizeTeam(r.team) === target)
  }, [rawRows, teamFilter])

  // Text filters (Customer / Order / Origin / Destination / Posted by /
  // Contract Type) on top of the team scope.
  const anyTextFilter = FILTER_FIELDS.some((f) => filters[f.key].trim() !== "")
  const rows = useMemo(() => {
    if (!anyTextFilter) return teamRows
    const customer = filters.customer.trim().toLowerCase()
    const order = filters.order.trim().toLowerCase()
    const origin = filters.origin.trim().toLowerCase()
    const destination = filters.destination.trim().toLowerCase()
    const carrier = filters.carrier.trim().toLowerCase()
    const postedBy = filters.postedBy.trim().toLowerCase()
    const contractType = filters.contractType.trim().toLowerCase()
    const equipmentType = filters.equipmentType.trim().toLowerCase()
    return teamRows.filter(
      (r) =>
        containsCi(r.customer, customer) &&
        containsCi(r.order_id, order) &&
        containsCi(r.origin, origin) &&
        containsCi(r.destination, destination) &&
        containsCi(r.carrier, carrier) &&
        containsCi(r.posted_by, postedBy) &&
        containsCi(r.contract_type, contractType) &&
        containsCi(r.equipment_type, equipmentType),
    )
  }, [teamRows, filters, anyTextFilter])

  // Recompute KPIs from the filtered rows so cards stay in sync with the table.
  // Backend KPI math uses the same rows + sum — safe to mirror here.
  const kpis = useMemo(() => {
    if (teamFilter === "all" && !anyTextFilter) return q.data?.data?.kpis
    let profit = 0
    let revenue = 0
    for (const r of rows) {
      if (typeof r.profit === "number") profit += r.profit
      if (typeof r.revenue === "number") revenue += r.revenue
    }
    return {
      loads: rows.length,
      profit,
      revenue,
      margin_pct: revenue > 0 ? profit / revenue : null,
    }
  }, [rows, teamFilter, anyTextFilter, q.data?.data?.kpis])

  // Podium medal lookup: top-3 by profit within the team scope (pre-search,
  // so a medal still marks the overall podium even while searching).
  const medalByOrder = useMemo(() => {
    const ranked = teamRows
      .filter((r): r is PodiumRow & { profit: number } =>
        typeof r.profit === "number" && r.profit > 0,
      )
      .slice()
      .sort((a, b) => (b.profit ?? 0) - (a.profit ?? 0))
    const map = new Map<string, string>()
    ranked.slice(0, 3).forEach((r, idx) => {
      if (!r.order_id) return
      map.set(r.order_id, ["🥇", "🥈", "🥉"][idx] ?? "")
    })
    return map
  }, [teamRows])

  // Shared client-side column sort (SPEC-CODE-RULES §38). No defaultKey →
  // backend order (posted_date DESC, profit DESC, revenue DESC) until a
  // header is clicked.
  const sort = useSortable(rows)

  const lastUpdated = q.dataUpdatedAt ? new Date(q.dataUpdatedAt) : null

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Header */}
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
          <Trophy className="h-4 w-4 text-[#C2410C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">Podium Set DFW</h1>
          <span className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-xs text-[#92400E]">
            DFW
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          {q.isFetching && (
            <span className="inline-flex items-center gap-1 text-[#6B7280]">
              <Loader2 className="h-3 w-3 animate-spin" />
              Refreshing
            </span>
          )}
          {lastUpdated && (
            <span>
              Last updated{" "}
              {lastUpdated.toLocaleTimeString("en-US", {
                hour: "2-digit",
                minute: "2-digit",
              })}{" "}
              CST
            </span>
          )}
          <span className="text-[#9CA3AF]">·</span>
          <span>Auto-refresh every 15 min</span>
        </div>
      </div>

      {/* Range + Team toggles */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Range
            </span>
            <div className="inline-flex rounded-md border border-[#E5E7EB] bg-white p-0.5">
              {RANGE_OPTIONS.map((o) => (
                <button
                  key={o.key}
                  onClick={() => setRange(o.key)}
                  className={
                    range === o.key
                      ? "rounded px-3 py-1 text-xs font-semibold bg-[#1B3A5C] text-white"
                      : "rounded px-3 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
                  }
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Team
            </span>
            <div className="inline-flex rounded-md border border-[#E5E7EB] bg-white p-0.5">
              {TEAM_OPTIONS.map((o) => (
                <button
                  key={o.key}
                  onClick={() => setTeamFilter(o.key)}
                  className={
                    teamFilter === o.key
                      ? "rounded px-3 py-1 text-xs font-semibold bg-[#C2410C] text-white"
                      : "rounded px-3 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
                  }
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>

          <span className="ml-auto text-xs text-[#9CA3AF]">
            TEAM-DFW · Rate Conf Received
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-4 px-6 py-5">
        {q.error ? (
          <div className="rounded-md border border-[#FCA5A5] bg-[#FEF2F2] px-3 py-2 text-xs text-[#991B1B]">
            Failed to load Podium Set DFW data.
            {q.error instanceof Error ? ` (${q.error.message})` : ""}
          </div>
        ) : null}

        {/* Filters — Customer / Order / Origin / Destination / Posted by / Contract Type */}
        <section className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-2.5">
          <div className="flex flex-wrap items-end gap-3">
            {FILTER_FIELDS.map((f) => (
              <label key={f.key} className="flex min-w-[180px] flex-1 flex-col gap-1 md:max-w-[280px]">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
                  {f.label}
                </span>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#9CA3AF]" />
                  <input
                    type="text"
                    value={filters[f.key]}
                    onChange={(e) =>
                      setFilters((prev) => ({ ...prev, [f.key]: e.target.value }))
                    }
                    placeholder={f.placeholder}
                    className="w-full rounded-md border border-[#E5E7EB] bg-white py-1.5 pl-7 pr-7 text-xs text-[#111827] placeholder:text-[#9CA3AF] focus:border-[#1B3A5C] focus:outline-none focus:ring-1 focus:ring-[#1B3A5C]"
                  />
                  {filters[f.key] !== "" && (
                    <button
                      onClick={() => setFilters((prev) => ({ ...prev, [f.key]: "" }))}
                      className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-[#9CA3AF] hover:bg-[#F3F4F6] hover:text-[#374151]"
                      aria-label={`Clear ${f.label} filter`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </label>
            ))}
            {anyTextFilter && (
              <button
                onClick={() => setFilters(EMPTY_FILTERS)}
                className="inline-flex items-center gap-1 rounded-md border border-[#E5E7EB] px-2.5 py-1.5 text-xs text-[#374151] hover:bg-[#F3F4F6]"
              >
                <X className="h-3.5 w-3.5" />
                Clear all
              </button>
            )}
          </div>
          {anyTextFilter && (
            <p className="mt-1.5 text-[11px] text-[#6B7280]">
              Showing {rows.length} of {teamRows.length} row
              {teamRows.length === 1 ? "" : "s"} — KPI cards reflect the filtered set.
            </p>
          )}
        </section>

        {/* KPI cards */}
        <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <KpiCard label="Loads"    value={fmtInt(kpis?.loads)}         color="#DC2626" />
          <KpiCard label="Profit"   value={fmtCurrency(kpis?.profit)}   color="#C2410C" />
          <KpiCard label="Revenue"  value={fmtCurrency(kpis?.revenue)}  color="#0F766E" />
          <KpiCard label="Margin %" value={fmtPct(kpis?.margin_pct)}    color="#1B3A5C" />
        </section>

        {/* Table */}
        <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white">
          <div className="flex items-center justify-between border-b border-[#E5E7EB] px-3 py-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[#374151]">
              Bookings {rangeLabel(range)}
            </h2>
            <span className="text-xs text-[#9CA3AF]">
              {rows.length} row{rows.length === 1 ? "" : "s"}
            </span>
          </div>

          {q.isLoading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-[#6B7280]">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading…
            </div>
          ) : rows.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
              <Trophy className="h-6 w-6 text-[#D1D5DB]" />
              {anyTextFilter && teamRows.length > 0 ? (
                <>
                  <p className="text-sm text-[#374151]">
                    No rows match the current filters.
                  </p>
                  <button
                    onClick={() => setFilters(EMPTY_FILTERS)}
                    className="text-xs text-[#1B3A5C] underline hover:text-[#111827]"
                  >
                    Clear filters
                  </button>
                </>
              ) : (
                <>
                  <p className="text-sm text-[#374151]">
                    No loads posted yet {rangeLabel(range).toLowerCase()}.
                  </p>
                  <p className="text-xs text-[#9CA3AF]">
                    Rate Confirmations will appear here as soon as they hit McLeod.
                  </p>
                </>
              )}
            </div>
          ) : (
            <div className="max-h-[calc(100vh-260px)] overflow-auto">
              <table className="w-full border-separate border-spacing-0 text-xs">
                <thead className="sticky top-0 z-10 bg-[#F3F4F6] text-[#374151]">
                  <tr>
                    <SortableTh label="Team"          columnKey="team"          state={sort} className={TH_CLASS} />
                    <SortableTh label="#Order"        columnKey="order_id"      state={sort} className={TH_CLASS} />
                    <SortableTh label="Posted by"     columnKey="posted_by"     state={sort} className={TH_CLASS} />
                    <SortableTh label="Date"          columnKey="posted_date"   state={sort} className={TH_CLASS} />
                    <SortableTh label="Customer"      columnKey="customer"      state={sort} className={TH_CLASS} />
                    <SortableTh label="Origin"        columnKey="origin"        state={sort} className={TH_CLASS} />
                    <SortableTh label="Destination"   columnKey="destination"   state={sort} className={TH_CLASS} />
                    <SortableTh label="Profit"        columnKey="profit"        state={sort} className={TH_CLASS} align="right" />
                    <SortableTh label="Revenue"       columnKey="revenue"       state={sort} className={TH_CLASS} align="right" />
                    <SortableTh label="Margin %"      columnKey="margin_pct"    state={sort} className={TH_CLASS} align="right" />
                    <SortableTh label="Contract Type" columnKey="contract_type" state={sort} className={TH_CLASS} />
                    <SortableTh label="Equipment Type" columnKey="equipment_type" state={sort} className={TH_CLASS} />
                    <SortableTh label="Carrier"       columnKey="carrier"       state={sort} className={TH_CLASS} />
                  </tr>
                </thead>
                <tbody>
                  {sort.sorted.map((r, idx) => {
                    const medal = r.order_id ? medalByOrder.get(r.order_id) : undefined
                    return (
                      <tr
                        key={`${r.order_id ?? "?"}-${idx}`}
                        className="odd:bg-white even:bg-[#FAFBFC] hover:bg-[#F3F4F6]"
                      >
                        <Td>{r.team ?? "—"}</Td>
                        <Td className="font-mono">
                          {medal && (
                            <span className="mr-1" title="Top profit today">
                              {medal}
                            </span>
                          )}
                          {r.order_id ?? "—"}
                        </Td>
                        <Td>{r.posted_by ?? "—"}</Td>
                        <Td className="whitespace-nowrap">{fmtDateTime(r.posted_date)}</Td>
                        <Td>{r.customer ?? "—"}</Td>
                        <Td>{r.origin ?? "—"}</Td>
                        <Td>{r.destination ?? "—"}</Td>
                        <Td className="text-right tabular-nums">
                          {fmtCurrency(r.profit)}
                        </Td>
                        <Td className="text-right tabular-nums">
                          {fmtCurrency(r.revenue)}
                        </Td>
                        <Td className="text-right tabular-nums">
                          {fmtPct(r.margin_pct)}
                        </Td>
                        <Td>{r.contract_type ?? "—"}</Td>
                        <Td>
                          <span title={r.equipment_type ?? undefined}>
                            {r.equipment_type ? r.equipment_type.slice(0, 10) : "—"}
                          </span>
                        </Td>
                        <Td>{r.carrier ?? "—"}</Td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function rangeLabel(r: PodiumRange): string {
  return r === "today" ? "Today" : r === "wtd" ? "Week to Date" : "Month to Date"
}

function KpiCard({
  label,
  value,
  color,
}: {
  label: string
  value: string
  color: string
}) {
  return (
    <div
      className="rounded-lg border bg-white p-3"
      style={{ borderColor: `${color}33` }}
    >
      <div
        className="text-[10px] font-semibold uppercase tracking-wider"
        style={{ color }}
      >
        {label}
      </div>
      <div
        className="mt-1 text-2xl font-semibold tabular-nums"
        style={{ color }}
      >
        {value}
      </div>
    </div>
  )
}

// Match the report's original header look on the shared <SortableTh>.
const TH_CLASS = "border-b border-[#E5E7EB] text-[11px] uppercase tracking-wider"

function Td({
  children,
  className = "",
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <td
      className={`border-b border-[#F3F4F6] px-3 py-1.5 text-[#111827] ${className}`}
    >
      {children}
    </td>
  )
}

