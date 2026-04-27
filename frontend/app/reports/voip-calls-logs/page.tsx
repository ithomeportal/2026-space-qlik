"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Phone,
  Search,
  X,
} from "lucide-react"
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  fmtDateTime,
  fmtHours,
  fmtInt,
  fmtIsoDay,
  fmtMin,
  fmtPct,
  useVoipByDirection,
  useVoipByHour,
  useVoipDetail,
  useVoipHeatmap,
  useVoipSummary,
  useVoipTopUsers,
  useVoipTrend,
  type VoipDirection,
  type VoipFilters,
  type VoipRange,
} from "@/lib/voip-calls-api"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const RANGE_OPTIONS: { key: VoipRange; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "wtd", label: "WTD" },
  { key: "last_7d", label: "Last 7d" },
  { key: "mtd", label: "MTD" },
  { key: "last_month", label: "Last Month" },
  { key: "ytd", label: "YTD" },
  { key: "custom", label: "Custom" },
]

const DIR_OPTIONS: { key: VoipDirection; label: string; color: string }[] = [
  { key: "ALL", label: "All", color: "#1B3A5C" },
  { key: "INBOUND", label: "Inbound", color: "#16A34A" },
  { key: "OUTBOUND", label: "Outbound", color: "#2563EB" },
  { key: "INTRA_PBX", label: "Intra PBX", color: "#7C3AED" },
]

const PIE_COLORS: Record<string, string> = {
  INBOUND: "#16A34A",
  OUTBOUND: "#2563EB",
  INTRA_PBX: "#7C3AED",
}

const PAGE_LIMIT = 200

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function VoipCallsLogsPage() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["voip-calls-logs"]]}>
      <VoipCallsLogsContent />
    </RoleGuard>
  )
}

function VoipCallsLogsContent() {
  const [range, setRange] = useState<VoipRange>("wtd")
  const [direction, setDirection] = useState<VoipDirection>("ALL")
  const [search, setSearch] = useState<string>("")
  const [searchInput, setSearchInput] = useState<string>("")
  const [startDate, setStartDate] = useState<string>("")
  const [endDate, setEndDate] = useState<string>("")
  const [page, setPage] = useState<number>(1)
  const [sort, setSort] = useState<string>("start_desc")

  const filters: VoipFilters = useMemo(
    () => ({
      range,
      direction,
      q: search || undefined,
      startDate: range === "custom" ? startDate || undefined : undefined,
      endDate: range === "custom" ? endDate || undefined : undefined,
    }),
    [range, direction, search, startDate, endDate],
  )

  const summaryQ = useVoipSummary(filters)
  const dirQ = useVoipByDirection(filters)
  const trendQ = useVoipTrend(filters)
  const hourQ = useVoipByHour(filters)
  const heatQ = useVoipHeatmap(filters)
  const topQ = useVoipTopUsers(filters, 10)
  const detailQ = useVoipDetail(filters, page, PAGE_LIMIT, sort)

  const summary = summaryQ.data?.data
  const dir = dirQ.data?.data ?? []
  const trend = trendQ.data?.data ?? []
  const hour = hourQ.data?.data ?? []
  const heat = heatQ.data?.data ?? []
  const top = topQ.data?.data
  const rows = detailQ.data?.data ?? []
  const total = detailQ.data?.meta?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_LIMIT))

  const window = summaryQ.data?.meta?.window
  const windowLabel =
    window?.start && window?.end
      ? window.start === window.end
        ? fmtIsoDay(window.start) + "/" + window.start.slice(0, 4)
        : `${fmtIsoDay(window.start)} → ${fmtIsoDay(window.end)}`
      : "—"

  function clearFilters() {
    setRange("wtd")
    setDirection("ALL")
    setSearch("")
    setSearchInput("")
    setStartDate("")
    setEndDate("")
    setPage(1)
  }

  function applySearch() {
    setSearch(searchInput.trim())
    setPage(1)
  }

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      <DesktopOnlyBanner />

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
          <Phone className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">VoIP Calls Logs</h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-xs text-[#1E40AF]">IT</span>
        </div>
        <div className="ml-auto text-xs text-[#6B7280]">
          {windowLabel}
          {direction !== "ALL" ? ` · ${direction}` : ""}
          {search ? ` · "${search}"` : ""}
        </div>
      </div>

      {/* Sticky filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          {/* Range pills */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
              Date
            </span>
            <div className="inline-flex flex-wrap rounded-md border border-[#E5E7EB] bg-white p-0.5">
              {RANGE_OPTIONS.map((o) => (
                <button
                  key={o.key}
                  onClick={() => {
                    setRange(o.key)
                    setPage(1)
                  }}
                  className={
                    range === o.key
                      ? "rounded px-2.5 py-1 text-xs font-semibold bg-[#1B3A5C] text-white"
                      : "rounded px-2.5 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
                  }
                >
                  {o.label}
                </button>
              ))}
            </div>
            {range === "custom" && (
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => {
                    setStartDate(e.target.value)
                    setPage(1)
                  }}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
                />
                <span className="text-xs text-[#9CA3AF]">→</span>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => {
                    setEndDate(e.target.value)
                    setPage(1)
                  }}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
                />
              </div>
            )}
          </div>

          {/* Direction pills */}
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
              Direction
            </span>
            <div className="inline-flex rounded-md border border-[#E5E7EB] bg-white p-0.5">
              {DIR_OPTIONS.map((o) => (
                <button
                  key={o.key}
                  onClick={() => {
                    setDirection(o.key)
                    setPage(1)
                  }}
                  className={
                    direction === o.key
                      ? "rounded px-2.5 py-1 text-xs font-semibold text-white"
                      : "rounded px-2.5 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
                  }
                  style={direction === o.key ? { background: o.color } : undefined}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>

          {/* Free-text search */}
          <div className="flex items-center gap-1 rounded-md border border-[#E5E7EB] bg-white px-2 py-1">
            <Search className="h-3.5 w-3.5 text-[#9CA3AF]" />
            <input
              type="text"
              placeholder="User, extension, phone…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") applySearch()
                if (e.key === "Escape") {
                  setSearchInput("")
                  setSearch("")
                }
              }}
              className="w-44 bg-transparent text-xs outline-none placeholder:text-[#9CA3AF]"
            />
            {searchInput && (
              <button
                onClick={() => {
                  setSearchInput("")
                  setSearch("")
                  setPage(1)
                }}
                className="text-[#9CA3AF] hover:text-[#374151]"
                aria-label="Clear search"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
            <button
              onClick={applySearch}
              className="ml-1 rounded bg-[#1B3A5C] px-2 py-0.5 text-[10px] font-semibold uppercase text-white hover:bg-[#15314e]"
            >
              Apply
            </button>
          </div>

          {(range !== "wtd" || direction !== "ALL" || search) && (
            <button
              onClick={clearFilters}
              className="ml-auto rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs text-[#6B7280] hover:bg-[#F3F4F6]"
            >
              Reset
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-4 px-6 py-5">
        <ErrorBanner
          errors={[
            summaryQ.error,
            dirQ.error,
            trendQ.error,
            hourQ.error,
            heatQ.error,
            topQ.error,
            detailQ.error,
          ]}
        />

        {/* KPI strip */}
        <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <KpiCard
            label="Total Calls"
            value={fmtInt(summary?.total_calls)}
            color="#1B3A5C"
            loading={summaryQ.isLoading}
          />
          <KpiCard
            label="Unique Users"
            value={fmtInt(summary?.unique_users)}
            color="#0F766E"
            loading={summaryQ.isLoading}
          />
          <KpiCard
            label="Avg Duration"
            value={fmtMin(summary?.avg_duration_min)}
            color="#7C3AED"
            loading={summaryQ.isLoading}
          />
          <KpiCard
            label="Total Talk-Time"
            value={fmtHours(summary?.total_duration_min)}
            color="#C2410C"
            loading={summaryQ.isLoading}
          />
          <KpiCard
            label="% Inbound"
            sub={`vs ${fmtPct(summary?.pct_outbound ?? 0)} Outbound`}
            value={fmtPct(summary?.pct_inbound)}
            color="#16A34A"
            loading={summaryQ.isLoading}
          />
          <KpiCard
            label="% Short Calls (<30s)"
            value={fmtPct(summary?.pct_short_calls)}
            color="#DC2626"
            loading={summaryQ.isLoading}
          />
        </section>

        {/* Row 1 — pie + combo */}
        <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Panel title="Call Direction" loading={dirQ.isLoading}>
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={dir}
                  dataKey="count"
                  nameKey="direction"
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={90}
                  paddingAngle={2}
                  label={(props: { direction?: string | number; percent?: number }) =>
                    `${props.direction ?? "?"} ${(((props.percent ?? 0) * 100) || 0).toFixed(1)}%`
                  }
                  labelLine={false}
                >
                  {dir.map((d) => (
                    <Cell
                      key={d.direction}
                      fill={PIE_COLORS[d.direction] ?? "#6B7280"}
                    />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(v) => fmtInt(Number(v))}
                />
              </PieChart>
            </ResponsiveContainer>
          </Panel>

          <Panel
            className="lg:col-span-2"
            title="# Calls vs Avg Duration (per day)"
            loading={trendQ.isLoading}
          >
            {trend.length === 0 ? (
              <EmptyState text="No calls in the selected window." />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart
                  data={trend.map((t) => ({
                    ...t,
                    label: fmtIsoDay(t.day),
                    avg_duration_min:
                      t.avg_duration_min === null ? 0 : Number(t.avg_duration_min.toFixed(2)),
                  }))}
                >
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                  <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fontSize: 10 }}
                    tickFormatter={(v) => `${v}m`}
                  />
                  <Tooltip
                    formatter={(v, name) =>
                      name === "Avg Duration (Min)"
                        ? `${Number(v).toFixed(2)} min`
                        : fmtInt(Number(v))
                    }
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar
                    yAxisId="left"
                    dataKey="count"
                    fill="#1B3A5C"
                    name="Count"
                    barSize={20}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="avg_duration_min"
                    stroke="#C2410C"
                    name="Avg Duration (Min)"
                    dot={{ r: 2 }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </Panel>
        </section>

        {/* Row 2 — heatmap + top users */}
        <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Panel
            className="lg:col-span-2"
            title="Day-of-Week × Hour heatmap (call count)"
            loading={heatQ.isLoading}
          >
            <Heatmap points={heat} />
          </Panel>
          <Panel title="Top 10 Users" loading={topQ.isLoading}>
            <TopUsers
              byCount={top?.by_count ?? []}
              byTalkTime={top?.by_talk_time ?? []}
            />
          </Panel>
        </section>

        {/* Row 3 — hour-of-day */}
        <Panel title="# Calls by Hour of Day (selected window)" loading={hourQ.isLoading}>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={hour}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="hour"
                tick={{ fontSize: 10 }}
                tickFormatter={(h) => `${h}:00`}
              />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip
                formatter={(v) => fmtInt(Number(v))}
                labelFormatter={(h) => `${h}:00 – ${h}:59`}
              />
              <Line
                type="monotone"
                dataKey="count"
                stroke="#1B3A5C"
                strokeWidth={2}
                dot={{ r: 3 }}
                name="Calls"
              />
            </LineChart>
          </ResponsiveContainer>
        </Panel>

        {/* Detail table */}
        <section className="rounded-lg border border-[#E5E7EB] bg-white">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E5E7EB] px-4 py-2">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-[#111827]">Call Details</h2>
              <span className="text-xs text-[#6B7280]">
                {fmtInt(total)} row{total === 1 ? "" : "s"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-[#6B7280]">Sort</label>
              <select
                value={sort}
                onChange={(e) => {
                  setSort(e.target.value)
                  setPage(1)
                }}
                className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
              >
                <option value="start_desc">Start (newest)</option>
                <option value="start_asc">Start (oldest)</option>
                <option value="duration_desc">Duration (longest)</option>
                <option value="duration_asc">Duration (shortest)</option>
                <option value="user_asc">User A→Z</option>
              </select>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-[#F9FAFB] text-[#6B7280]">
                <tr>
                  <Th>Type</Th>
                  <Th>Start</Th>
                  <Th>User</Th>
                  <Th>Identif</Th>
                  <Th>Call Details</Th>
                  <Th>End</Th>
                  <Th>Call ID</Th>
                  <Th className="text-right">Duration (Min)</Th>
                </tr>
              </thead>
              <tbody>
                {detailQ.isLoading && rows.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-3 py-6 text-center text-[#9CA3AF]">
                      <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-3 py-6 text-center text-[#9CA3AF]">
                      No calls in this window.
                    </td>
                  </tr>
                ) : (
                  rows.map((r, i) => (
                    <tr
                      key={`${r.call_id ?? "?"}-${i}`}
                      className="border-t border-[#F3F4F6] hover:bg-[#F9FAFB]"
                    >
                      <Td>
                        <DirectionBadge direction={r.type} />
                      </Td>
                      <Td className="whitespace-nowrap">{fmtDateTime(r.start)}</Td>
                      <Td>{r.username || <span className="text-[#9CA3AF]">—</span>}</Td>
                      <Td>{r.identif || <span className="text-[#9CA3AF]">—</span>}</Td>
                      <Td className="text-[#374151]">{r.call_details || "—"}</Td>
                      <Td className="whitespace-nowrap">{fmtDateTime(r.end)}</Td>
                      <Td className="font-mono text-[10px] text-[#6B7280]">
                        <CopyOnClick text={r.call_id} />
                      </Td>
                      <Td className="text-right tabular-nums">
                        {fmtMin(r.duration_min)}
                      </Td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-[#E5E7EB] px-4 py-2 text-xs text-[#6B7280]">
              <div>
                Page {page} of {totalPages}
              </div>
              <div className="flex items-center gap-1">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="rounded-md border border-[#E5E7EB] bg-white p-1 hover:bg-[#F3F4F6] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronLeft className="h-3 w-3" />
                </button>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  className="rounded-md border border-[#E5E7EB] bg-white p-1 hover:bg-[#F3F4F6] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronRight className="h-3 w-3" />
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
// Sub-components
// ---------------------------------------------------------------------------

function DesktopOnlyBanner() {
  return (
    <div className="block bg-[#FEF3C7] px-4 py-2 text-center text-[11px] text-[#92400E] xl:hidden">
      Best viewed on a desktop ≥1280px wide. Some panels may overflow on small
      screens.
    </div>
  )
}

function ErrorBanner({ errors }: { errors: Array<unknown> }) {
  const real = errors.find((e) => e instanceof Error) as Error | undefined
  if (!real) return null
  return (
    <div className="rounded-md border border-[#FCA5A5] bg-[#FEF2F2] px-3 py-2 text-xs text-[#991B1B]">
      Failed to load some panels: {real.message}
    </div>
  )
}

function Panel({
  title,
  children,
  loading,
  className = "",
}: {
  title: string
  children: React.ReactNode
  loading?: boolean
  className?: string
}) {
  return (
    <div className={`rounded-lg border border-[#E5E7EB] bg-white p-3 ${className}`}>
      <h2 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#374151]">
        {title}
        {loading && <Loader2 className="h-3 w-3 animate-spin text-[#9CA3AF]" />}
      </h2>
      {children}
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex h-[220px] items-center justify-center text-xs text-[#9CA3AF]">
      {text}
    </div>
  )
}

function KpiCard({
  label,
  value,
  sub,
  color,
  loading,
}: {
  label: string
  value: string
  sub?: string
  color: string
  loading?: boolean
}) {
  return (
    <div
      className="rounded-lg border bg-white px-3 py-2"
      style={{ borderColor: `${color}33` }}
    >
      <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color }}>
        {label}
      </div>
      <div
        className="mt-1 text-2xl font-semibold tabular-nums leading-none"
        style={{ color }}
      >
        {loading ? <span className="text-[#9CA3AF]">…</span> : value}
      </div>
      {sub && <div className="mt-1 text-[10px] text-[#9CA3AF]">{sub}</div>}
    </div>
  )
}

function DirectionBadge({ direction }: { direction: string | null }) {
  if (!direction) return <span className="text-[#9CA3AF]">—</span>
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    INBOUND:   { bg: "#DCFCE7", fg: "#166534", label: "Inbound" },
    OUTBOUND:  { bg: "#DBEAFE", fg: "#1E40AF", label: "Outbound" },
    INTRA_PBX: { bg: "#EDE9FE", fg: "#5B21B6", label: "Intra PBX" },
  }
  const c = cfg[direction] ?? { bg: "#F3F4F6", fg: "#374151", label: direction }
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
      style={{ background: c.bg, color: c.fg }}
    >
      {c.label}
    </span>
  )
}

function CopyOnClick({ text }: { text: string | null }) {
  const [copied, setCopied] = useState(false)
  if (!text) return <>—</>
  return (
    <button
      title={copied ? "Copied!" : "Click to copy"}
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1200)
        })
      }}
      className="text-left hover:text-[#1B3A5C]"
    >
      {text.length > 12 ? `${text.slice(0, 8)}…${text.slice(-4)}` : text}
      {copied && <span className="ml-1 text-[#16A34A]">✓</span>}
    </button>
  )
}

// Inline-SVG day-of-week × hour heatmap. Cell color scales with cell.count
// (linear, anchored to max). Row label = day, col label = hour.
function Heatmap({ points }: { points: { dow: number; hour: number; count: number }[] }) {
  const grid = useMemo(() => {
    const g: number[][] = Array.from({ length: 7 }, () => Array(24).fill(0))
    for (const p of points) {
      if (p.dow >= 0 && p.dow < 7 && p.hour >= 0 && p.hour < 24) {
        g[p.dow][p.hour] = p.count
      }
    }
    return g
  }, [points])

  const max = useMemo(() => {
    let m = 0
    for (const row of grid) for (const v of row) if (v > m) m = v
    return m
  }, [grid])

  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

  if (max === 0) {
    return <EmptyState text="No calls in the selected window." />
  }

  // Cell size — keep the panel close to 240px tall.
  const cellH = 22
  const cellW = 26
  const gridW = cellW * 24
  const totalW = 38 + gridW + 8
  const totalH = 18 + cellH * 7 + 18

  function colorFor(v: number): string {
    if (!v) return "#F3F4F6"
    const t = v / max
    // Sequential blue scale. Higher t = darker.
    const r = Math.round(219 - 195 * t)
    const g = Math.round(234 - 154 * t)
    const b = Math.round(254 - 122 * t)
    return `rgb(${r}, ${g}, ${b})`
  }

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${totalW} ${totalH}`} width="100%" className="block">
        {/* Hour column labels (every 3 hrs) */}
        {Array.from({ length: 24 }, (_, h) => h).map((h) => (
          <text
            key={`h-${h}`}
            x={38 + h * cellW + cellW / 2}
            y={12}
            fontSize={9}
            textAnchor="middle"
            fill="#6B7280"
          >
            {h % 3 === 0 ? `${h}` : ""}
          </text>
        ))}
        {/* Day labels + cells */}
        {grid.map((row, d) => (
          <g key={`row-${d}`}>
            <text
              x={32}
              y={18 + d * cellH + cellH / 2 + 3}
              fontSize={10}
              textAnchor="end"
              fill="#374151"
            >
              {days[d]}
            </text>
            {row.map((v, h) => (
              <g key={`c-${d}-${h}`}>
                <rect
                  x={38 + h * cellW + 1}
                  y={18 + d * cellH + 1}
                  width={cellW - 2}
                  height={cellH - 2}
                  fill={colorFor(v)}
                  rx={2}
                />
                {v > 0 && v >= max * 0.4 && (
                  <text
                    x={38 + h * cellW + cellW / 2}
                    y={18 + d * cellH + cellH / 2 + 3}
                    fontSize={9}
                    textAnchor="middle"
                    fill="#1B3A5C"
                  >
                    {v}
                  </text>
                )}
                <title>{`${days[d]} ${h}:00 — ${v} calls`}</title>
              </g>
            ))}
          </g>
        ))}
      </svg>
      <div className="mt-1 flex items-center gap-2 text-[10px] text-[#6B7280]">
        <span>Less</span>
        <div className="flex">
          {[0.0, 0.25, 0.5, 0.75, 1.0].map((t, i) => (
            <span
              key={i}
              className="inline-block h-3 w-5"
              style={{ background: colorFor(Math.round(max * t)) }}
            />
          ))}
        </div>
        <span>More</span>
        <span className="ml-auto text-[#9CA3AF]">peak {fmtInt(max)} calls/hr</span>
      </div>
    </div>
  )
}

function TopUsers({
  byCount,
  byTalkTime,
}: {
  byCount: { username: string; calls: number; minutes: number }[]
  byTalkTime: { username: string; calls: number; minutes: number }[]
}) {
  const [tab, setTab] = useState<"calls" | "time">("calls")
  const list = tab === "calls" ? byCount : byTalkTime
  const max = list.reduce(
    (m, r) => Math.max(m, tab === "calls" ? r.calls : r.minutes),
    0,
  )

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 inline-flex self-start rounded-md border border-[#E5E7EB] bg-white p-0.5">
        <button
          onClick={() => setTab("calls")}
          className={
            tab === "calls"
              ? "rounded px-2 py-0.5 text-[11px] font-semibold bg-[#1B3A5C] text-white"
              : "rounded px-2 py-0.5 text-[11px] text-[#374151] hover:bg-[#F3F4F6]"
          }
        >
          By Calls
        </button>
        <button
          onClick={() => setTab("time")}
          className={
            tab === "time"
              ? "rounded px-2 py-0.5 text-[11px] font-semibold bg-[#1B3A5C] text-white"
              : "rounded px-2 py-0.5 text-[11px] text-[#374151] hover:bg-[#F3F4F6]"
          }
        >
          By Talk-Time
        </button>
      </div>
      {list.length === 0 ? (
        <EmptyState text="No users in this window." />
      ) : (
        <ul className="space-y-1">
          {list.slice(0, 10).map((r) => {
            const v = tab === "calls" ? r.calls : r.minutes
            const pct = max > 0 ? (v / max) * 100 : 0
            return (
              <li key={r.username} className="text-[11px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[#111827]" title={r.username}>
                    {r.username}
                  </span>
                  <span className="tabular-nums text-[#374151]">
                    {tab === "calls" ? fmtInt(v) : fmtMin(v)}
                  </span>
                </div>
                <div className="mt-0.5 h-1 rounded bg-[#F3F4F6]">
                  <div
                    className="h-1 rounded"
                    style={{
                      width: `${pct.toFixed(1)}%`,
                      background: tab === "calls" ? "#1B3A5C" : "#C2410C",
                    }}
                  />
                </div>
              </li>
            )
          })}
        </ul>
      )}
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
      className={`px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider ${className}`}
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
  return <td className={`px-3 py-2 text-[#111827] ${className}`}>{children}</td>
}
