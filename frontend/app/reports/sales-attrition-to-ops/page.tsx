"use client"

import { Suspense, useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, ArrowUpDown, Loader2, UserMinus } from "lucide-react"
import {
  useSaopDetails,
  useSaopFilters,
  useSaopTrend,
  type SaopBucket,
  type SaopDetailsRow,
  type SaopFilters,
  type SaopRange,
  type SaopTrendPoint,
} from "@/lib/sales-attrition-to-ops-api"
import { ErrorBanner } from "./ErrorBanner"
import { fmtInt, fmtMoney, fmtPct, fmtDate } from "./format"

const ALL_TEAMS = [
  "TEAM1",
  "TEAM2",
  "TEAM3",
  "TEAM4",
  "TEAM5",
  "TEAM-DFW",
] as const

const BUCKET_OPTIONS: { key: SaopBucket; label: string }[] = [
  { key: "", label: "All days" },
  { key: "1_30", label: "1–30d" },
  { key: "31_90", label: "31–90d" },
  { key: "91_180", label: "91–180d" },
  { key: "181_365", label: "181–365d" },
  { key: "365_plus", label: "365+d" },
]

const RANGE_OPTIONS: { key: SaopRange; label: string }[] = [
  { key: "last_365", label: "Last 365d" },
  { key: "mtd", label: "MTD" },
  { key: "last_month", label: "Last month" },
  { key: "ytd", label: "YTD" },
  { key: "custom", label: "Custom" },
]

type SortKey =
  | "days_desc"
  | "days_asc"
  | "loads_desc"
  | "loads_asc"
  | "revenue_desc"
  | "revenue_asc"
  | "profit_desc"
  | "profit_asc"
  | "margin_desc"
  | "margin_asc"
  | "customer_asc"

function SaopContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  const range = (searchParams.get("range") as SaopRange) || "last_365"
  const startDate = searchParams.get("start_date") || ""
  const endDate = searchParams.get("end_date") || ""
  const teamsParam = searchParams.get("teams")
  const teams = useMemo<string[]>(() => {
    if (teamsParam === null) return [...ALL_TEAMS]
    if (teamsParam === "") return []
    return teamsParam
      .split(",")
      .filter((t) => (ALL_TEAMS as readonly string[]).includes(t))
  }, [teamsParam])
  const customer = searchParams.get("customer") || ""
  const bucket = (searchParams.get("bucket") as SaopBucket) || ""
  const sort = (searchParams.get("sort") as SortKey) || "days_desc"
  const page = Math.max(1, Number(searchParams.get("page") || "1"))
  const limit = 100

  const updateUrl = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      const next = new URLSearchParams(searchParams.toString())
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === undefined || v === "") next.delete(k)
        else next.set(k, v)
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [searchParams, router, pathname],
  )

  const setRange = (r: SaopRange) =>
    updateUrl({ range: r === "last_365" ? null : r, page: null })
  const setCustomDate = (which: "start" | "end", v: string) =>
    updateUrl({ [`${which}_date`]: v || null, page: null })
  const setCustomer = (c: string) => updateUrl({ customer: c || null, page: null })
  const setBucket = (b: SaopBucket) => updateUrl({ bucket: b || null, page: null })
  const setSort = (s: SortKey) => updateUrl({ sort: s === "days_desc" ? null : s, page: null })
  const setPage = (p: number) => updateUrl({ page: p === 1 ? null : String(p) })
  const setTeams = (next: string[]) => {
    if (next.length === ALL_TEAMS.length) updateUrl({ teams: null, page: null })
    else updateUrl({ teams: next.join(","), page: null })
  }
  const toggleTeam = (t: string) => {
    setTeams(teams.includes(t) ? teams.filter((x) => x !== t) : [...teams, t])
  }
  const allTeamsSelected = teams.length === ALL_TEAMS.length

  const filters: SaopFilters = useMemo(
    () => ({
      range,
      startDate: range === "custom" ? startDate || undefined : undefined,
      endDate: range === "custom" ? endDate || undefined : undefined,
      teams,
      customer: customer || undefined,
      bucket: bucket || undefined,
    }),
    [range, startDate, endDate, teams, customer, bucket],
  )

  const { data: filterRes, isLoading: loadingFilters } = useSaopFilters()
  const filterOptions = filterRes?.data
  const detailsQ = useSaopDetails(filters, sort, page, limit)
  const trendQ = useSaopTrend(teams, customer || undefined)

  const [customerInput, setCustomerInput] = useState<string>("")
  const customerSuggestions = useMemo(() => {
    const q = customerInput.trim().toLowerCase()
    if (!q || !filterOptions?.customers) return []
    return filterOptions.customers
      .filter((c) => c.toLowerCase().includes(q))
      .slice(0, 8)
  }, [customerInput, filterOptions])

  const totals = detailsQ.data?.data?.totals
  const rows = detailsQ.data?.data?.rows ?? []
  const totalRows = detailsQ.data?.meta?.total ?? 0
  const trend = trendQ.data?.data?.series ?? []

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Mobile gate */}
      <div className="border-b border-[#FDE68A] bg-[#FEF3C7] px-4 py-2 text-xs text-[#92400E] xl:hidden">
        <strong>Best viewed on desktop.</strong> The 13-month trend strip and
        sparkline-rich detail table are dense; mobile rendering is limited.
      </div>

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
          <UserMinus className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">
            Sales- Attrition to OPs
          </h1>
          <span className="rounded-full bg-[#FEE2E2] px-2 py-0.5 text-[10px] text-[#991B1B]">
            customer attrition signal
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          <span>
            Teams: {allTeamsSelected ? "All" : teams.join(", ") || "None"}
            {customer ? ` · Customer: ${customer}` : ""}
          </span>
        </div>
      </div>

      {/* Filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          {/* Date range */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Date
            </label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {RANGE_OPTIONS.map((r) => (
                <button
                  key={r.key}
                  onClick={() => setRange(r.key)}
                  className={`px-3 py-1.5 ${
                    range === r.key
                      ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                      : "text-[#6B7280] hover:text-[#111827]"
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
            {range === "custom" && (
              <div className="flex items-center gap-1">
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setCustomDate("start", e.target.value)}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
                />
                <span className="text-[#6B7280]">→</span>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setCustomDate("end", e.target.value)}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
                />
              </div>
            )}
          </div>

          {/* Teams */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Teams
            </label>
            <div className="flex flex-wrap gap-1">
              {ALL_TEAMS.map((t) => {
                const on = teams.includes(t)
                return (
                  <button
                    key={t}
                    onClick={() => toggleTeam(t)}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      on
                        ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                        : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                    }`}
                  >
                    {t}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Customer */}
          <div className="relative flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Customer
            </label>
            <input
              type="text"
              placeholder={
                loadingFilters ? "Loading…" : customer || "All customers"
              }
              value={customerInput}
              onChange={(e) => setCustomerInput(e.target.value)}
              onBlur={() => setTimeout(() => setCustomerInput(""), 150)}
              className="w-64 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            />
            {customerInput && customerSuggestions.length > 0 && (
              <ul className="absolute left-[calc(theme(spacing.2)+4.5rem)] top-full z-30 mt-1 max-h-64 w-64 overflow-auto rounded-md border border-[#E5E7EB] bg-white text-xs shadow-md">
                {customerSuggestions.map((c) => (
                  <li key={c}>
                    <button
                      onMouseDown={() => {
                        setCustomer(c)
                        setCustomerInput("")
                      }}
                      className="block w-full truncate px-3 py-1.5 text-left hover:bg-[#F3F4F6]"
                    >
                      {c}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {customer && (
              <button
                onClick={() => setCustomer("")}
                className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs text-[#6B7280] hover:bg-[#F3F4F6]"
              >
                Clear
              </button>
            )}
          </div>

          {loadingFilters && (
            <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />
          )}
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 px-6 py-6 space-y-6">
        <ErrorBanner
          errors={[detailsQ.error, trendQ.error]}
          label="Sales Attrition"
        />

        {/* Trend strip — fixed 13-month window, ignores Date filter */}
        <section className="rounded-lg border border-[#E5E7EB] bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[#111827]">
              13-month trend
              <span className="ml-2 text-xs font-normal text-[#6B7280]">
                — fixed window, does not change with the Date filter
              </span>
            </h2>
            {trendQ.isFetching && (
              <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />
            )}
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <TrendChart
              title="#Loads"
              accent="#10B981"
              data={trend}
              format={(p) => fmtInt(p.loads)}
              accessor={(p) => p.loads}
            />
            <TrendChart
              title="$Profit"
              accent="#F59E0B"
              data={trend}
              format={(p) => fmtMoney(p.profit, { compact: true })}
              accessor={(p) => p.profit}
              allowNegative
            />
            <TrendChart
              title="%Margin"
              accent="#A855F7"
              data={trend}
              format={(p) => (p.margin_pct == null ? "—" : fmtPct(p.margin_pct))}
              accessor={(p) => (p.margin_pct ?? 0) * 100}
              allowNegative
            />
          </div>
        </section>

        {/* KPI strip — honors Date / Teams / Customer */}
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <KpiCard label="Customers" value={fmtInt(totals?.customers ?? 0)} />
          <KpiCard label="Loads" value={fmtInt(totals?.loads ?? 0)} />
          <KpiCard label="Revenue" value={fmtMoney(totals?.revenue ?? 0)} />
          <KpiCard
            label="Profit"
            value={fmtMoney(totals?.profit ?? 0)}
            tone={(totals?.profit ?? 0) < 0 ? "neg" : "neutral"}
          />
          <KpiCard
            label="Margin"
            value={
              totals?.margin_pct == null ? "—" : fmtPct(totals.margin_pct)
            }
            tone={
              totals?.margin_pct == null
                ? "neutral"
                : totals.margin_pct < 0
                  ? "neg"
                  : totals.margin_pct < 0.05
                    ? "warn"
                    : "pos"
            }
          />
        </section>

        {/* Days bucket pills */}
        <section className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
            Days since last load
          </span>
          {BUCKET_OPTIONS.map((b) => {
            const on = bucket === b.key
            return (
              <button
                key={b.key || "all"}
                onClick={() => setBucket(b.key)}
                className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                  on
                    ? "border-[#991B1B] bg-[#991B1B] text-white"
                    : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                }`}
              >
                {b.label}
              </button>
            )
          })}
          <span className="ml-auto text-xs text-[#6B7280]">
            {totalRows.toLocaleString()} customer
            {totalRows === 1 ? "" : "s"}
            {detailsQ.isFetching ? " · loading…" : ""}
          </span>
        </section>

        {/* Detail table */}
        <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-[#F9FAFB] text-left text-[10px] uppercase tracking-wider text-[#6B7280]">
                <tr>
                  <SortableTh label="Customer" k="customer_asc" sort={sort} setSort={setSort} />
                  <th className="px-3 py-2 font-semibold">Team</th>
                  <SortableTh label="#Loads" k="loads_desc" altK="loads_asc" sort={sort} setSort={setSort} numeric />
                  <SortableTh label="$Revenue" k="revenue_desc" altK="revenue_asc" sort={sort} setSort={setSort} numeric />
                  <SortableTh label="$Profit" k="profit_desc" altK="profit_asc" sort={sort} setSort={setSort} numeric />
                  <SortableTh label="%Margin" k="margin_desc" altK="margin_asc" sort={sort} setSort={setSort} numeric />
                  <th className="px-3 py-2 font-semibold">Last Load</th>
                  <SortableTh label="#Days" k="days_desc" altK="days_asc" sort={sort} setSort={setSort} numeric />
                  <th className="px-3 py-2 font-semibold">8w trend</th>
                </tr>
              </thead>
              <tbody>
                {/* Totals row — sticky on top */}
                {totals && (
                  <tr className="border-b border-[#E5E7EB] bg-[#F3F4F6] font-semibold">
                    <td className="px-3 py-2">Totals</td>
                    <td className="px-3 py-2 text-[#6B7280]">—</td>
                    <td className="px-3 py-2 text-right">{fmtInt(totals.loads)}</td>
                    <td className="px-3 py-2 text-right">{fmtMoney(totals.revenue)}</td>
                    <td className={`px-3 py-2 text-right ${totals.profit < 0 ? "text-[#991B1B]" : ""}`}>
                      {fmtMoney(totals.profit)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {totals.margin_pct == null ? "—" : fmtPct(totals.margin_pct)}
                    </td>
                    <td className="px-3 py-2 text-[#6B7280]">—</td>
                    <td className="px-3 py-2 text-right">—</td>
                    <td className="px-3 py-2"></td>
                  </tr>
                )}
                {detailsQ.isLoading && (
                  <tr>
                    <td colSpan={9} className="px-3 py-8 text-center text-[#6B7280]">
                      <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />
                      Loading customers…
                    </td>
                  </tr>
                )}
                {!detailsQ.isLoading && rows.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-3 py-8 text-center text-[#6B7280]">
                      No customers match the current filters.
                    </td>
                  </tr>
                )}
                {rows.map((r) => (
                  <DetailRow key={`${r.customer}-${r.team ?? ""}`} row={r} />
                ))}
              </tbody>
            </table>
          </div>

          {/* Pager */}
          {totalRows > limit && (
            <div className="flex items-center justify-between border-t border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2 text-xs text-[#6B7280]">
              <span>
                Page {page} of {Math.max(1, Math.ceil(totalRows / limit))} ·{" "}
                {totalRows.toLocaleString()} rows
              </span>
              <div className="flex gap-1">
                <button
                  onClick={() => setPage(Math.max(1, page - 1))}
                  disabled={page === 1}
                  className="rounded border border-[#E5E7EB] bg-white px-2 py-1 disabled:opacity-50"
                >
                  Prev
                </button>
                <button
                  onClick={() => setPage(page + 1)}
                  disabled={page * limit >= totalRows}
                  className="rounded border border-[#E5E7EB] bg-white px-2 py-1 disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Detail row — color-coded #Days, sparkline, money/pct formatting
// ---------------------------------------------------------------------------

function DetailRow({ row }: { row: SaopDetailsRow }) {
  const days = row.days_since
  const daysCls =
    days == null
      ? "bg-[#F3F4F6] text-[#6B7280]"
      : days <= 30
        ? "bg-[#D1FAE5] text-[#065F46]"
        : days <= 90
          ? "bg-[#FEF3C7] text-[#92400E]"
          : days <= 180
            ? "bg-[#FED7AA] text-[#9A3412]"
            : "bg-[#FEE2E2] text-[#991B1B]"

  const profitCls =
    row.profit < 0 ? "text-[#991B1B]" : row.profit > 0 ? "text-[#065F46]" : ""
  const marginCls =
    row.margin_pct == null
      ? "text-[#6B7280]"
      : row.margin_pct < 0
        ? "text-[#991B1B]"
        : row.margin_pct < 0.05
          ? "text-[#92400E]"
          : ""

  return (
    <tr className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]">
      <td className="max-w-[18rem] truncate px-3 py-1.5 font-medium text-[#111827]" title={row.customer}>
        {row.customer}
      </td>
      <td className="px-3 py-1.5 text-[#374151]">{row.team || "—"}</td>
      <td className="px-3 py-1.5 text-right tabular-nums">{fmtInt(row.loads)}</td>
      <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(row.revenue)}</td>
      <td className={`px-3 py-1.5 text-right tabular-nums ${profitCls}`}>
        {fmtMoney(row.profit)}
      </td>
      <td className={`px-3 py-1.5 text-right tabular-nums ${marginCls}`}>
        {row.margin_pct == null ? "—" : fmtPct(row.margin_pct)}
      </td>
      <td className="px-3 py-1.5 text-[#374151]">
        {row.last_load_date ? fmtDate(row.last_load_date) : "—"}
      </td>
      <td className="px-3 py-1.5 text-right">
        <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold tabular-nums ${daysCls}`}>
          {days == null ? "—" : days}
        </span>
      </td>
      <td className="px-3 py-1.5">
        <Sparkline values={row.sparkline} />
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Sparkline — inline 8-week #Loads mini chart
// ---------------------------------------------------------------------------

function Sparkline({ values }: { values: number[] }) {
  if (!values || values.length === 0) {
    return <span className="text-[10px] text-[#6B7280]">—</span>
  }
  const max = Math.max(1, ...values)
  const w = 80
  const h = 18
  const step = w / Math.max(1, values.length)
  const points = values
    .map((v, i) => {
      const x = i * step + step / 2
      const y = h - (v / max) * h
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")
  const last = values[values.length - 1]
  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      className="inline-block"
      role="img"
      aria-label={`8-week loads sparkline, latest ${last}`}
    >
      <polyline
        points={points}
        fill="none"
        stroke="#1B3A5C"
        strokeWidth={1.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={(values.length - 1) * step + step / 2}
        cy={h - (last / max) * h}
        r={1.8}
        fill="#1B3A5C"
      />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Trend chart — single-series bar chart (pure SVG, ~80 LOC)
// ---------------------------------------------------------------------------

function TrendChart({
  title,
  accent,
  data,
  format,
  accessor,
  allowNegative = false,
}: {
  title: string
  accent: string
  data: SaopTrendPoint[]
  format: (p: SaopTrendPoint) => string
  accessor: (p: SaopTrendPoint) => number
  allowNegative?: boolean
}) {
  const w = 360
  const h = 140
  const pad = { top: 20, right: 6, bottom: 22, left: 6 }
  const innerW = w - pad.left - pad.right
  const innerH = h - pad.top - pad.bottom

  const values = data.map(accessor)
  const max = Math.max(0, ...values)
  const min = allowNegative ? Math.min(0, ...values) : 0
  const span = Math.max(1, max - min)
  const zeroY = pad.top + (max / span) * innerH
  const barW = data.length === 0 ? 0 : Math.max(2, (innerW / data.length) * 0.7)
  const step = data.length === 0 ? 0 : innerW / data.length

  return (
    <div className="rounded-md border border-[#F3F4F6] bg-[#FAFAFA] p-3">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-xs font-semibold text-[#111827]">{title}</span>
        <span className="text-[10px] text-[#6B7280]">last 13 months</span>
      </div>
      {data.length === 0 ? (
        <div className="flex h-[140px] items-center justify-center text-xs text-[#6B7280]">
          No data
        </div>
      ) : (
        <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img">
          <line
            x1={pad.left}
            x2={w - pad.right}
            y1={zeroY}
            y2={zeroY}
            stroke="#E5E7EB"
            strokeWidth={1}
          />
          {data.map((p, i) => {
            const v = accessor(p)
            const xCenter = pad.left + i * step + step / 2
            const x = xCenter - barW / 2
            const top =
              v >= 0
                ? pad.top + ((max - v) / span) * innerH
                : zeroY
            const height =
              v >= 0
                ? zeroY - top
                : ((Math.abs(v)) / span) * innerH
            return (
              <g key={p.month}>
                <rect
                  x={x}
                  y={top}
                  width={barW}
                  height={Math.max(0.5, height)}
                  fill={accent}
                  opacity={0.85}
                  rx={1}
                >
                  <title>{`${shortMonth(p.month)} · ${format(p)}`}</title>
                </rect>
              </g>
            )
          })}
          {data.map((p, i) => (
            <text
              key={`lbl-${p.month}`}
              x={pad.left + i * step + step / 2}
              y={h - 6}
              fontSize={8.5}
              textAnchor="middle"
              fill="#6B7280"
            >
              {shortMonth(p.month)}
            </text>
          ))}
        </svg>
      )}
    </div>
  )
}

function shortMonth(iso: string): string {
  const d = new Date(iso + "T00:00:00")
  if (Number.isNaN(d.getTime())) return iso.slice(0, 7)
  const m = d.toLocaleString("en-US", { month: "short" })
  const y = String(d.getFullYear()).slice(-2)
  return `${m} ${y}`
}

// ---------------------------------------------------------------------------
// Sortable header + KPI card
// ---------------------------------------------------------------------------

function SortableTh({
  label,
  k,
  altK,
  sort,
  setSort,
  numeric,
}: {
  label: string
  k: SortKey
  altK?: SortKey
  sort: SortKey
  setSort: (s: SortKey) => void
  numeric?: boolean
}) {
  const active = sort === k || sort === altK
  const onClick = () => {
    if (sort === k && altK) setSort(altK)
    else setSort(k)
  }
  return (
    <th className={`px-3 py-2 font-semibold ${numeric ? "text-right" : ""}`}>
      <button
        onClick={onClick}
        className={`inline-flex items-center gap-1 ${active ? "text-[#111827]" : "text-[#6B7280]"} hover:text-[#111827]`}
      >
        {label}
        <ArrowUpDown className="h-3 w-3" />
      </button>
    </th>
  )
}

function KpiCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string
  value: string
  tone?: "neutral" | "pos" | "neg" | "warn"
}) {
  const toneCls =
    tone === "pos"
      ? "text-[#065F46]"
      : tone === "neg"
        ? "text-[#991B1B]"
        : tone === "warn"
          ? "text-[#92400E]"
          : "text-[#111827]"
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${toneCls}`}>
        {value}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page wrapper (Suspense boundary required for useSearchParams)
// ---------------------------------------------------------------------------

export default function SaopPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center text-xs text-[#6B7280]">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading…
        </div>
      }
    >
      <SaopContent />
    </Suspense>
  )
}
