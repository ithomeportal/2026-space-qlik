"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { ArrowLeft, Loader2, Trophy } from "lucide-react"
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
  const q = usePodiumOverview(range)

  const rawRows = q.data?.data?.rows ?? []

  // Filter rows by team (client-side — datalake already returns all DFW rows).
  const rows = useMemo(() => {
    if (teamFilter === "all") return rawRows
    const target = teamFilter.toUpperCase()
    return rawRows.filter((r) => normalizeTeam(r.team) === target)
  }, [rawRows, teamFilter])

  // Recompute KPIs from the filtered rows so cards stay in sync with the table.
  // Backend KPI math uses the same rows + sum — safe to mirror here.
  const kpis = useMemo(() => {
    if (teamFilter === "all") return q.data?.data?.kpis
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
  }, [rows, teamFilter, q.data?.data?.kpis])

  // Podium medal lookup: top-3 by profit (descending, nulls excluded).
  const medalByOrder = useMemo(() => {
    const ranked = rows
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
  }, [rows])

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
              <p className="text-sm text-[#374151]">
                No loads posted yet {rangeLabel(range).toLowerCase()}.
              </p>
              <p className="text-xs text-[#9CA3AF]">
                Rate Confirmations will appear here as soon as they hit McLeod.
              </p>
            </div>
          ) : (
            <div className="max-h-[calc(100vh-260px)] overflow-auto">
              <table className="w-full border-separate border-spacing-0 text-xs">
                <thead className="sticky top-0 z-10 bg-[#F3F4F6] text-[#374151]">
                  <tr>
                    <Th>Team</Th>
                    <Th>#Order</Th>
                    <Th>Posted by</Th>
                    <Th>Date</Th>
                    <Th>Customer</Th>
                    <Th>Origin</Th>
                    <Th>Destination</Th>
                    <Th className="text-right">Profit</Th>
                    <Th className="text-right">Revenue</Th>
                    <Th className="text-right">Margin %</Th>
                    <Th>Contract Type</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, idx) => {
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

function Th({
  children,
  className = "",
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <th
      className={`border-b border-[#E5E7EB] px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider ${className}`}
    >
      {children}
    </th>
  )
}

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

