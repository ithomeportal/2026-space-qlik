"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  LifeBuoy,
  Loader2,
} from "lucide-react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  agingBand,
  fmtDateTime,
  fmtInt,
  fmtIsoDay,
  fmtPct,
  useItTicketsSummary,
  useItTicketsTable,
  type ItTicketsFilters,
  type ItTicketsRange,
  type ItTicketsType,
} from "@/lib/it-tickets-api"
import { ReportGuard } from "@/components/ReportGuard"
// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const RANGE_OPTIONS: { key: ItTicketsRange; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "wtd", label: "WTD" },
  { key: "last_7d", label: "Last 7d" },
  { key: "last_30d", label: "Last 30d" },
  { key: "mtd", label: "MTD" },
  { key: "last_month", label: "Last Month" },
  { key: "ytd", label: "YTD" },
  { key: "custom", label: "Custom" },
]

const TYPE_OPTIONS: { key: ItTicketsType; label: string }[] = [
  { key: "service_request", label: "Service Request" },
  { key: "incident", label: "Incidents" },
]

// Stable category palette (matches Bruno's pastel set)
const CATEGORY_COLORS: Record<string, string> = {
  Hardware: "#7C3AED",
  Maintenance: "#E6D7C3",
  McLeod: "#1B3A5C",
  Outlook: "#5E92C2",
  "Unilink Portal": "#7CA982",
  Other: "#9CA3AF",
  External: "#80B4C7",
  DAT: "#D6CFC0",
  Admin: "#264653",
  Pricing: "#A0392B",
  "Time off portal": "#9F86C0",
  Vonage: "#2A9D8F",
  Network: "#118AB2",
  Sinch: "#06D6A0",
  Software: "#F4A261",
  Mobile: "#E76F51",
  Barracuda: "#84A98C",
  Teams: "#B9375E",
  "My Carrier Portal": "#3D5A80",
  "New PC Program": "#577590",
  "Update Employee Info": "#90BE6D",
}

const STATUS_COLORS: Record<string, string> = {
  Pending: "#5EEAD4",
  Open: "#A78BFA",
  "In Progress": "#3B82F6",
  "Waiting for user response": "#A0392B",
  Closed: "#E6D7C3",
  Resolved: "#1B3A5C",
}

const PRIORITY_COLORS: Record<string, string> = {
  Low: "#1B3A5C",
  Medium: "#A0392B",
  High: "#F59E0B",
  Urgent: "#DC2626",
  Unset: "#9CA3AF",
}

const PAGE_SIZE = 50

function colorForCategory(name: string): string {
  return CATEGORY_COLORS[name] ?? "#94A3B8"
}

function colorForStatus(name: string): string {
  return STATUS_COLORS[name] ?? "#94A3B8"
}

function colorForPriority(name: string): string {
  return PRIORITY_COLORS[name] ?? "#94A3B8"
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ItTicketsMgmtPage() {
  return (
    <ReportGuard reportKey="it-tickets-mgmt">
      <ItTicketsMgmtContent />
    </ReportGuard>
  )
}

function ItTicketsMgmtContent() {
  const [type, setType] = useState<ItTicketsType>("service_request")
  const [range, setRange] = useState<ItTicketsRange>("last_30d")
  const [startDate, setStartDate] = useState<string>("")
  const [endDate, setEndDate] = useState<string>("")
  const [historyTab, setHistoryTab] = useState<"status" | "category">("status")
  const [tableTab, setTableTab] = useState<"pending" | "closed">("pending")
  const [pendingPage, setPendingPage] = useState<number>(1)
  const [closedPage, setClosedPage] = useState<number>(1)
  const [pendingSort, setPendingSort] = useState<string | null>(null)
  const [closedSort, setClosedSort] = useState<string | null>(null)

  const filters: ItTicketsFilters = useMemo(
    () => ({
      type,
      range,
      startDate: range === "custom" ? startDate || undefined : undefined,
      endDate: range === "custom" ? endDate || undefined : undefined,
    }),
    [type, range, startDate, endDate],
  )

  const summaryQ = useItTicketsSummary(filters)
  const pendingQ = useItTicketsTable(
    filters,
    "pending",
    pendingPage,
    PAGE_SIZE,
    pendingSort,
  )
  const closedQ = useItTicketsTable(
    filters,
    "closed",
    closedPage,
    PAGE_SIZE,
    closedSort,
  )

  const summary = summaryQ.data?.data
  const kpis = summary?.kpis
  const window = summary?.range

  const pendingRows = pendingQ.data?.data ?? []
  const closedRows = closedQ.data?.data ?? []
  const pendingTotal = pendingQ.data?.meta?.total ?? 0
  const closedTotal = closedQ.data?.meta?.total ?? 0
  const pendingPages = Math.max(1, Math.ceil(pendingTotal / PAGE_SIZE))
  const closedPages = Math.max(1, Math.ceil(closedTotal / PAGE_SIZE))

  const windowLabel =
    window?.start && window?.end
      ? window.start === window.end
        ? fmtIsoDay(window.start)
        : `${fmtIsoDay(window.start)} → ${fmtIsoDay(window.end)}`
      : "—"

  // Pivot by_month / by_week_pending / by_day_pending into Recharts series
  const monthSeries = useMemo(
    () => pivotByCategory(summary?.by_month ?? [], "month_start", "month_label"),
    [summary?.by_month],
  )
  const weekSeries = useMemo(
    () => pivotByCategory(summary?.by_week_pending ?? [], "week_start"),
    [summary?.by_week_pending],
  )
  const daySeries = useMemo(
    () => pivotByCategory(summary?.by_day_pending ?? [], "day"),
    [summary?.by_day_pending],
  )
  const historyStatusSeries = useMemo(
    () =>
      pivotByKey(summary?.history_status ?? [], "day", (r) =>
        String(r.status ?? "Unknown"),
      ),
    [summary?.history_status],
  )
  const monthCategories = monthSeries.categories
  const weekCategories = weekSeries.categories
  const dayCategories = daySeries.categories
  const historyStatuses = historyStatusSeries.categories

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
          <LifeBuoy className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">IT Tickets Mgmt</h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-xs text-[#1E40AF]">IT</span>
        </div>
        <div className="ml-auto text-xs text-[#6B7280]">{windowLabel}</div>
      </div>

      {/* Sticky filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          {/* Type tabs */}
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
              Type
            </span>
            <div className="inline-flex rounded-md border border-[#E5E7EB] bg-white p-0.5">
              {TYPE_OPTIONS.map((o) => (
                <button
                  key={o.key}
                  onClick={() => {
                    setType(o.key)
                    setPendingPage(1)
                    setClosedPage(1)
                  }}
                  className={
                    type === o.key
                      ? "rounded px-3 py-1 text-xs font-semibold bg-[#1B3A5C] text-white"
                      : "rounded px-3 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
                  }
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>

          {/* Date range pills */}
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
                    setPendingPage(1)
                    setClosedPage(1)
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
                    setPendingPage(1)
                    setClosedPage(1)
                  }}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
                />
                <span className="text-xs text-[#9CA3AF]">→</span>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => {
                    setEndDate(e.target.value)
                    setPendingPage(1)
                    setClosedPage(1)
                  }}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
                />
              </div>
            )}
          </div>
        </div>
      </div>

      <main className="mx-auto w-full max-w-[1920px] flex-1 px-6 py-4">
        <ErrorBanner
          errors={[summaryQ.error, pendingQ.error, closedQ.error]}
        />

        {/* KPIs */}
        <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard
            label={type === "incident" ? "Pending Tickets Now" : "Pending Services Now"}
            value={fmtInt(kpis?.pending_now ?? 0)}
            tone="blue"
            loading={summaryQ.isLoading}
          />
          <KpiCard
            label="% Open"
            value={fmtPct(kpis?.pct_open ?? 0)}
            tone="blue"
            loading={summaryQ.isLoading}
          />
          <KpiCard
            label={type === "incident" ? "Closed Tickets" : "Closed Tickets Serv"}
            value={fmtInt(kpis?.closed ?? 0)}
            tone="green"
            loading={summaryQ.isLoading}
          />
          <KpiCard
            label="% Closed"
            value={fmtPct(kpis?.pct_closed ?? 0)}
            tone="green"
            loading={summaryQ.isLoading}
          />
        </div>

        {/* Pending by Month + Status/Priority pies */}
        <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
          <Panel
            title="# Pending Tickets by Month"
            subtitle="Last 12 months · ignores Date filter"
            loading={summaryQ.isLoading}
            className="xl:col-span-2"
          >
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={monthSeries.rows} margin={{ top: 16, right: 12, left: 0, bottom: 4 }}>
                <CartesianGrid stroke="#F3F4F6" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip cursor={{ fill: "#F3F4F6" }} />
                <Legend wrapperStyle={{ fontSize: 11 }} iconSize={10} />
                {monthCategories.map((c) => (
                  <Bar
                    key={c}
                    dataKey={c}
                    stackId="cat"
                    fill={colorForCategory(c)}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </Panel>

          <div className="grid grid-cols-2 gap-4">
            <Panel title="Status (pending)" loading={summaryQ.isLoading}>
              <DonutChart
                data={(summary?.status ?? []).map((r) => ({
                  name: r.status,
                  value: r.cnt,
                  color: colorForStatus(r.status),
                }))}
              />
            </Panel>
            <Panel title="Priority (pending)" loading={summaryQ.isLoading}>
              <DonutChart
                data={(summary?.priority ?? []).map((r) => ({
                  name: r.priority,
                  value: r.cnt,
                  color: colorForPriority(r.priority),
                }))}
              />
            </Panel>
          </div>
        </div>

        {/* Pending by Week + Pending by Day */}
        <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Panel
            title="Created Date by Week — Pending"
            subtitle="ISO Mon-Sun, current included"
            loading={summaryQ.isLoading}
          >
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={weekSeries.rows} margin={{ top: 12, right: 8, left: 0, bottom: 4 }}>
                <CartesianGrid stroke="#F3F4F6" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip cursor={{ fill: "#F3F4F6" }} />
                <Legend wrapperStyle={{ fontSize: 11 }} iconSize={10} />
                {weekCategories.map((c) => (
                  <Bar
                    key={c}
                    dataKey={c}
                    stackId="cat"
                    fill={colorForCategory(c)}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </Panel>

          <Panel
            title="Created Date by Day — Pending"
            subtitle="One bar per day in selected window"
            loading={summaryQ.isLoading}
          >
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={daySeries.rows} margin={{ top: 12, right: 8, left: 0, bottom: 4 }}>
                <CartesianGrid stroke="#F3F4F6" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip cursor={{ fill: "#F3F4F6" }} />
                <Legend wrapperStyle={{ fontSize: 11 }} iconSize={10} />
                {dayCategories.map((c) => (
                  <Bar
                    key={c}
                    dataKey={c}
                    stackId="cat"
                    fill={colorForCategory(c)}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </Panel>
        </div>

        {/* Agents + History */}
        <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
          <Panel
            title="Agents Assignments (pending)"
            subtitle="Joined via ResponderId"
            loading={summaryQ.isLoading}
          >
            <ResponsiveContainer width="100%" height={260}>
              <BarChart
                data={(summary?.by_agent ?? []).map((r) => ({ name: r.agent, value: r.cnt }))}
                margin={{ top: 16, right: 8, left: 0, bottom: 4 }}
              >
                <CartesianGrid stroke="#F3F4F6" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip cursor={{ fill: "#F3F4F6" }} />
                <Bar dataKey="value" fill="#1B3A5C" />
              </BarChart>
            </ResponsiveContainer>
          </Panel>

          <Panel
            title={
              type === "incident" ? "Incidents History" : "Services Request History"
            }
            subtitle={
              historyTab === "status"
                ? "Stacked by Status · respects Date filter"
                : "Bar by Category · respects Date filter"
            }
            loading={summaryQ.isLoading}
            className="xl:col-span-2"
            actions={
              <div className="inline-flex rounded-md border border-[#E5E7EB] bg-white p-0.5">
                <button
                  onClick={() => setHistoryTab("status")}
                  className={
                    historyTab === "status"
                      ? "rounded px-2.5 py-1 text-xs font-semibold bg-[#1B3A5C] text-white"
                      : "rounded px-2.5 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
                  }
                >
                  Status
                </button>
                <button
                  onClick={() => setHistoryTab("category")}
                  className={
                    historyTab === "category"
                      ? "rounded px-2.5 py-1 text-xs font-semibold bg-[#1B3A5C] text-white"
                      : "rounded px-2.5 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
                  }
                >
                  Category
                </button>
              </div>
            }
          >
            {historyTab === "status" ? (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart
                  data={historyStatusSeries.rows}
                  margin={{ top: 16, right: 8, left: 0, bottom: 4 }}
                >
                  <CartesianGrid stroke="#F3F4F6" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip cursor={{ fill: "#F3F4F6" }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} iconSize={10} />
                  {historyStatuses.map((s) => (
                    <Bar
                      key={s}
                      dataKey={s}
                      stackId="status"
                      fill={colorForStatus(s)}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart
                  data={(summary?.history_category ?? []).map((r) => ({
                    name: r.category,
                    value: r.cnt,
                  }))}
                  margin={{ top: 16, right: 8, left: 0, bottom: 32 }}
                >
                  <CartesianGrid stroke="#F3F4F6" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0} angle={-30} textAnchor="end" height={48} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip cursor={{ fill: "#F3F4F6" }} />
                  <Bar dataKey="value" fill="#1B3A5C" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Panel>
        </div>

        {/* Detail tables */}
        <div className="rounded-lg border border-[#E5E7EB] bg-white">
          <div className="flex items-center gap-2 border-b border-[#E5E7EB] px-4 py-3">
            <button
              onClick={() => setTableTab("pending")}
              className={
                tableTab === "pending"
                  ? "rounded px-3 py-1 text-xs font-semibold bg-[#1B3A5C] text-white"
                  : "rounded px-3 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
              }
            >
              Pending Tickets Details ({fmtInt(pendingTotal)})
            </button>
            <button
              onClick={() => setTableTab("closed")}
              className={
                tableTab === "closed"
                  ? "rounded px-3 py-1 text-xs font-semibold bg-[#1B3A5C] text-white"
                  : "rounded px-3 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
              }
            >
              Closed Tickets Details ({fmtInt(closedTotal)})
            </button>
            <span className="ml-auto text-[11px] text-[#6B7280]">
              Page {tableTab === "pending" ? pendingPage : closedPage} of{" "}
              {tableTab === "pending" ? pendingPages : closedPages}
            </span>
            <button
              disabled={
                tableTab === "pending" ? pendingPage <= 1 : closedPage <= 1
              }
              onClick={() =>
                tableTab === "pending"
                  ? setPendingPage((p) => Math.max(1, p - 1))
                  : setClosedPage((p) => Math.max(1, p - 1))
              }
              className="rounded border border-[#E5E7EB] px-2 py-0.5 text-xs disabled:opacity-40"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <button
              disabled={
                tableTab === "pending"
                  ? pendingPage >= pendingPages
                  : closedPage >= closedPages
              }
              onClick={() =>
                tableTab === "pending"
                  ? setPendingPage((p) => Math.min(pendingPages, p + 1))
                  : setClosedPage((p) => Math.min(closedPages, p + 1))
              }
              className="rounded border border-[#E5E7EB] px-2 py-0.5 text-xs disabled:opacity-40"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>

          <TicketTable
            rows={tableTab === "pending" ? pendingRows : closedRows}
            loading={tableTab === "pending" ? pendingQ.isLoading : closedQ.isLoading}
            agingColored={tableTab === "pending"}
            sort={tableTab === "pending" ? pendingSort : closedSort}
            onSort={(s) => {
              if (tableTab === "pending") {
                setPendingSort(s)
                setPendingPage(1)
              } else {
                setClosedSort(s)
                setClosedPage(1)
              }
            }}
          />
        </div>
      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pivot helpers
// ---------------------------------------------------------------------------

interface PivotRow {
  key: string
  label: string
  [category: string]: string | number
}

function pivotByCategory(
  src: readonly unknown[],
  keyField: string,
  labelField?: string,
): { rows: PivotRow[]; categories: string[] } {
  const categoriesSet = new Set<string>()
  const byKey = new Map<string, PivotRow>()
  for (const raw of src) {
    const row = raw as Record<string, unknown>
    const k = String(row[keyField] ?? "")
    if (!k) continue
    const lbl = labelField
      ? String(row[labelField] ?? k)
      : prettyKey(keyField, k)
    if (!byKey.has(k)) {
      byKey.set(k, { key: k, label: lbl })
    }
    const cur = byKey.get(k)!
    const cat = String(row.category ?? "Other")
    cur[cat] = ((cur[cat] as number) ?? 0) + Number(row.cnt ?? 0)
    categoriesSet.add(cat)
  }
  const rows = Array.from(byKey.values()).sort((a, b) =>
    a.key < b.key ? -1 : a.key > b.key ? 1 : 0,
  )
  return { rows, categories: Array.from(categoriesSet).sort() }
}

function pivotByKey(
  src: readonly unknown[],
  keyField: string,
  bucketAccessor: (row: Record<string, unknown>) => string,
): { rows: PivotRow[]; categories: string[] } {
  const categoriesSet = new Set<string>()
  const byKey = new Map<string, PivotRow>()
  for (const raw of src) {
    const row = raw as Record<string, unknown>
    const k = String(row[keyField] ?? "")
    if (!k) continue
    if (!byKey.has(k)) {
      byKey.set(k, { key: k, label: prettyKey(keyField, k) })
    }
    const cur = byKey.get(k)!
    const bucket = bucketAccessor(row)
    cur[bucket] = ((cur[bucket] as number) ?? 0) + Number(row.cnt ?? 0)
    categoriesSet.add(bucket)
  }
  const rows = Array.from(byKey.values()).sort((a, b) =>
    a.key < b.key ? -1 : a.key > b.key ? 1 : 0,
  )
  return { rows, categories: Array.from(categoriesSet).sort() }
}

function prettyKey(keyField: string, k: string): string {
  if (keyField === "day" || keyField === "week_start") {
    const d = new Date(k)
    if (Number.isNaN(d.getTime())) return k
    return `${(d.getMonth() + 1).toString().padStart(2, "0")}/${d
      .getDate()
      .toString()
      .padStart(2, "0")}`
  }
  if (keyField === "month_start") {
    const d = new Date(k)
    if (Number.isNaN(d.getTime())) return k
    return d.toLocaleDateString("en-US", { month: "short", year: "numeric" })
  }
  return k
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DesktopOnlyBanner() {
  return (
    <div className="block bg-[#FEF3C7] px-4 py-2 text-center text-[11px] text-[#92400E] xl:hidden">
      Best viewed on a desktop ≥1280px wide. Some panels may overflow on small screens.
    </div>
  )
}

function ErrorBanner({ errors }: { errors: Array<unknown> }) {
  const real = errors.find((e) => e instanceof Error) as Error | undefined
  if (!real) return null
  return (
    <div className="mb-3 rounded-md border border-[#FCA5A5] bg-[#FEF2F2] px-3 py-2 text-xs text-[#991B1B]">
      Failed to load some panels: {real.message}
    </div>
  )
}

function KpiCard({
  label,
  value,
  tone,
  loading,
}: {
  label: string
  value: string
  tone: "blue" | "green"
  loading?: boolean
}) {
  const toneCls =
    tone === "green"
      ? "border-[#A7F3D0] bg-[#ECFDF5]"
      : "border-[#BFDBFE] bg-[#EFF6FF]"
  const numCls = tone === "green" ? "text-[#047857]" : "text-[#1B3A5C]"
  return (
    <div className={`rounded-lg border ${toneCls} px-5 py-4`}>
      <div className="text-xs text-[#6B7280]">{label}</div>
      <div className={`mt-1 text-3xl font-bold ${numCls}`}>
        {loading ? <span className="opacity-40">…</span> : value}
      </div>
    </div>
  )
}

function Panel({
  title,
  subtitle,
  children,
  loading,
  actions,
  className,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
  loading?: boolean
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <div className={`rounded-lg border border-[#E5E7EB] bg-white p-4 ${className ?? ""}`}>
      <div className="mb-2 flex items-start gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-[#1B3A5C]">{title}</div>
          {subtitle ? (
            <div className="truncate text-[11px] text-[#6B7280]">{subtitle}</div>
          ) : null}
        </div>
        {actions ? <div className="ml-auto">{actions}</div> : null}
      </div>
      {loading ? (
        <div className="flex h-[260px] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#9CA3AF]" />
        </div>
      ) : (
        children
      )}
    </div>
  )
}

interface DonutDatum {
  name: string
  value: number
  color: string
}

function DonutChart({ data }: { data: DonutDatum[] }) {
  const total = data.reduce((sum, d) => sum + d.value, 0)
  if (!total) {
    return (
      <div className="flex h-[260px] items-center justify-center text-xs text-[#9CA3AF]">
        No data
      </div>
    )
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          innerRadius={48}
          outerRadius={88}
          paddingAngle={1}
          stroke="#fff"
        >
          {data.map((d) => (
            <Cell key={d.name} fill={d.color} />
          ))}
        </Pie>
        <Tooltip />
        <Legend wrapperStyle={{ fontSize: 11 }} iconSize={10} />
      </PieChart>
    </ResponsiveContainer>
  )
}

interface ColumnDef {
  key: string
  label: string
  width?: string
  align?: "left" | "right"
  render?: (row: TicketRow) => React.ReactNode
}

interface TicketRow {
  id: number
  created: string | null
  category: string | null
  sub_category: string | null
  item_category: string | null
  agent: string | null
  name: string | null
  subject: string | null
  status: string | null
  due_by: string | null
  updated: string | null
}

function TicketTable({
  rows,
  loading,
  agingColored,
  sort,
  onSort,
}: {
  rows: TicketRow[]
  loading: boolean
  agingColored: boolean
  sort: string | null
  onSort: (s: string) => void
}) {
  const columns: ColumnDef[] = [
    { key: "id", label: "Id", width: "w-[6%]" },
    {
      key: "created",
      label: "Created",
      width: "w-[10%]",
      render: (r) => fmtIsoDay(r.created),
    },
    { key: "category", label: "Category", width: "w-[10%]" },
    { key: "sub_category", label: "SubCategory", width: "w-[10%]" },
    {
      key: "item_category",
      label: "ItemCategory",
      width: "w-[8%]",
      render: (r) => r.item_category || "—",
    },
    { key: "agent", label: "Agent", width: "w-[7%]" },
    { key: "name", label: "Name", width: "w-[12%]" },
    { key: "subject", label: "Subject" },
    { key: "status", label: "Status", width: "w-[10%]" },
    {
      key: "due_by",
      label: "DueBy",
      width: "w-[11%]",
      render: (r) => fmtDateTime(r.due_by),
    },
    {
      key: "updated",
      label: "UpdatedDate",
      width: "w-[11%]",
      render: (r) => fmtDateTime(r.updated),
    },
  ]

  const sortKey = sort?.replace(/^-/, "") ?? null
  const sortDir = sort?.startsWith("-") ? "DESC" : "ASC"

  function flipSort(key: string) {
    if (sortKey === key) {
      onSort(sortDir === "ASC" ? `-${key}` : key)
    } else {
      onSort(key)
    }
  }

  if (loading) {
    return (
      <div className="flex h-[280px] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[#9CA3AF]" />
      </div>
    )
  }

  if (!rows.length) {
    return (
      <div className="flex h-[120px] items-center justify-center text-xs text-[#6B7280]">
        No tickets in the selected window.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-[#1B3A5C] text-white">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={`px-2 py-2 text-left font-semibold ${c.width ?? ""}`}
              >
                <button
                  onClick={() => flipSort(c.key)}
                  className="inline-flex items-center gap-1 hover:underline"
                >
                  {c.label}
                  {sortKey === c.key ? (
                    <span className="text-[10px]">{sortDir === "ASC" ? "▲" : "▼"}</span>
                  ) : null}
                </button>
              </th>
            ))}
            {agingColored ? (
              <th className="px-2 py-2 text-right font-semibold w-[5%]">Age</th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const band = agingColored ? agingBand(r.created) : null
            return (
              <tr
                key={r.id}
                className={`border-b border-[#F3F4F6] ${band?.cls ?? ""}`}
              >
                {columns.map((c) => (
                  <td key={c.key} className="px-2 py-1.5 align-top">
                    {c.render
                      ? c.render(r)
                      : ((r as unknown as Record<string, unknown>)[c.key] as
                          | string
                          | number
                          | null) ?? "—"}
                  </td>
                ))}
                {band ? (
                  <td className="px-2 py-1.5 text-right text-[11px] tabular-nums text-[#374151]">
                    {band.label}
                  </td>
                ) : null}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
