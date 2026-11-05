"use client"

import { Suspense, useCallback, useMemo, useRef, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Hourglass, Loader2 } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import {
  DEFAULT_FILTERS,
  WINDOWS,
  useCustomers,
  type Division,
  type RangeKey,
  type ReportFilters,
  type Window,
} from "@/lib/customer-lifespan-api"
import { CohortsPanel } from "./CohortsPanel"
import { CustomerDrawer } from "./CustomerDrawer"
import { CustomerFilters, EMPTY_FILTERS, applyFilters, type Filters } from "./CustomerFilters"
import { CustomersPanel } from "./CustomersPanel"
import { DataSourcesBar } from "./DataSourcesBar"
import { KpiStrip } from "./KpiStrip"
import { LifespanFilterBar } from "./LifespanFilterBar"
import { LifespanPanel } from "./LifespanPanel"
import { SummaryPanel } from "./SummaryPanel"
import { TimelinePanel } from "./TimelinePanel"
import { TrendPanel } from "./TrendPanel"
import { Card, ErrorBox, Loading, Segmented } from "./ui"
import { FavoriteToggle } from "@/components/FavoriteToggle"

const TABS = [
  { k: "summary", label: "Summary" },
  { k: "trends", label: "Trends" },
  { k: "cohorts", label: "Cohorts" },
  { k: "lifespan", label: "Lifespan & Survival" },
  { k: "customers", label: "Customers" },
  { k: "timeline", label: "Timeline" },
] as const
type TabKey = (typeof TABS)[number]["k"]

const DIVISIONS = [
  { k: "all", label: "All" },
  { k: "corp", label: "CORP" },
  { k: "dfw", label: "DFW" },
] as const

const WINDOW_OPTIONS = WINDOWS.map((w) => ({ k: w, label: `${w} days` }))
const RANGE_KEYS: readonly { k: RangeKey }[] = [
  { k: "last_365" }, { k: "mtd" }, { k: "last_month" }, { k: "ytd" }, { k: "custom" }, { k: "all" },
]

function pick<T extends string | number>(raw: string | null, allowed: readonly { k: T }[], fallback: T): T {
  const hit = allowed.find((o) => String(o.k) === raw)
  return hit ? hit.k : fallback
}

function readFilters(params: URLSearchParams): ReportFilters {
  const teams = params.get("teams")
  return {
    range: pick<RangeKey>(params.get("range"), RANGE_KEYS, DEFAULT_FILTERS.range),
    start: params.get("start") ?? "",
    end: params.get("end") ?? "",
    teams: teams === null ? null : teams.split("|").filter(Boolean),
    customer: params.get("customer") ?? "",
  }
}

const isComplete = (f: ReportFilters) => f.range !== "custom" || (!!f.start && !!f.end && f.start <= f.end)

function filterNote(f: ReportFilters, window: Window): string | null {
  if (f.range === "all") return null
  const short = f.range === "mtd" || f.range === "last_month"
  return `Only customers and loads in these dates are counted; lifespans run from the first to the last load inside them. Choose All time for the full history.${
    short ? ` A month is shorter than the ${window} days it takes to call a customer lost, so At Risk and Lost read 0 here.` : ""
  }`
}

/** Customers + Timeline share one list and one set of filters. */
function CustomerTabs({ tab, division, window, filters, onOpen }: {
  tab: "customers" | "timeline"
  division: Division
  window: Window
  filters: ReportFilters
  onOpen: (id: string) => void
}) {
  const { data, error, isLoading } = useCustomers(division, window, filters)
  const [tabFilters, setTabFilters] = useState<Filters>(EMPTY_FILTERS)
  const rows = useMemo(() => data?.data ?? [], [data])
  const shown = useMemo(() => applyFilters(rows, tabFilters), [rows, tabFilters])
  const years = useMemo(() => Array.from(new Set(rows.map((r) => r.cohort_year))).sort(), [rows])
  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) return <Loading />
  return (
    <Card>
      <div className="mb-3">
        <CustomerFilters value={tabFilters} onChange={setTabFilters} years={years} shown={shown.length} total={rows.length} />
      </div>
      {tab === "customers"
        ? <CustomersPanel rows={shown} onOpen={onOpen} />
        : <TimelinePanel rows={shown} asOf={data.meta.as_of} onOpen={onOpen} />}
    </Card>
  )
}

function LifespanContent() {
  const router = useRouter()
  const pathname = usePathname()
  const params = useSearchParams()
  const tab = pick<TabKey>(params.get("tab"), TABS, "summary")
  const division = pick<Division>(params.get("division"), DIVISIONS, "all")
  const window = pick<Window>(params.get("window"), WINDOW_OPTIONS, 90)
  const barFilters = useMemo(() => readFilters(new URLSearchParams(params.toString())), [params])
  // Unfinished custom dates keep the last complete range on screen, not a 422 or another range.
  const lastDates = useRef<Pick<ReportFilters, "range" | "start" | "end">>(DEFAULT_FILTERS)
  const filters = useMemo(() => {
    if (!isComplete(barFilters)) return { ...barFilters, ...lastDates.current }
    lastDates.current = { range: barFilters.range, start: barFilters.start, end: barFilters.end }
    return barFilters
  }, [barFilters])
  const [openId, setOpenId] = useState<string | null>(null)
  const { data: customers } = useCustomers(division, window, filters)

  const replaceUrl = useCallback(
    (next: URLSearchParams) => {
      const qs = next.toString()
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    },
    [pathname, router],
  )

  const setParam = useCallback(
    (key: string, value: string, fallback: string) => {
      const next = new URLSearchParams(params.toString())
      if (value === fallback) next.delete(key)
      else next.set(key, value)
      replaceUrl(next)
    },
    [params, replaceUrl],
  )

  // Team chips differ per division: a selection from the other one would empty the report.
  const setDivision = useCallback(
    (value: Division) => {
      const next = new URLSearchParams(params.toString())
      next.delete("teams")
      if (value === "all") next.delete("division")
      else next.set("division", value)
      replaceUrl(next)
    },
    [params, replaceUrl],
  )

  const setFilters = useCallback(
    (patch: Partial<ReportFilters>) => {
      const merged = { ...barFilters, ...patch }
      const next = new URLSearchParams(params.toString())
      const put = (key: string, value: string | null) => (value ? next.set(key, value) : next.delete(key))
      put("range", merged.range === DEFAULT_FILTERS.range ? null : merged.range)
      put("start", merged.range === "custom" ? merged.start : null)
      put("end", merged.range === "custom" ? merged.end : null)
      put("customer", merged.customer)
      if (merged.teams === null) next.delete("teams")
      else next.set("teams", merged.teams.join("|"))
      replaceUrl(next)
    },
    [barFilters, params, replaceUrl],
  )

  const note = filterNote(filters, window)
  // Trends keeps a Years selection; a new population must not leave it pointing at empty years.
  const trendKey = [division, filters.range, filters.start, filters.end, filters.teams?.join("|"), filters.customer].join(":")

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <div className="flex flex-wrap items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link href="/" className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]">
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <Hourglass className="h-4 w-4 text-[#1B3A5C]" />
        <h1 className="text-sm font-semibold text-[#1B3A5C]">Customer Lifespan<FavoriteToggle /></h1>
        <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-xs text-[#1D4ED8]">TMS · since 2016</span>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <Segmented label="Division" value={division} options={DIVISIONS} onChange={setDivision} />
          <Segmented label="Lost after" value={window} options={WINDOW_OPTIONS} onChange={(v) => setParam("window", String(v), "90")} />
        </div>
      </div>
      <div className="mx-auto w-full max-w-[1600px] px-6 pt-4">
        <DataSourcesBar asOf={customers?.meta.data_as_of} />
      </div>
      <div className="pt-4">
        <LifespanFilterBar division={division} value={barFilters} onChange={setFilters} />
      </div>
      <div className="mx-auto w-full max-w-[1600px] space-y-4 px-6 py-4">
        {note && <p className="text-[11px] text-[#6B7280]">{note}</p>}
        <KpiStrip division={division} window={window} filters={filters} />
        <div className="flex w-fit flex-wrap rounded-lg border border-[#E5E7EB] bg-white text-xs">
          {TABS.map((t) => (
            <button
              key={t.k}
              onClick={() => setParam("tab", t.k, "summary")}
              className={`px-4 py-2 first:rounded-l-lg last:rounded-r-lg ${
                tab === t.k ? "bg-[#1B3A5C] font-semibold text-white" : "text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        {tab === "summary" && <SummaryPanel division={division} window={window} filters={filters} onOpen={setOpenId} />}
        {tab === "trends" && <TrendPanel key={trendKey} division={division} window={window} filters={filters} onOpen={setOpenId} />}
        {tab === "cohorts" && <CohortsPanel division={division} window={window} filters={filters} />}
        {tab === "lifespan" && <LifespanPanel division={division} window={window} filters={filters} onOpen={setOpenId} />}
        {(tab === "customers" || tab === "timeline") && (
          <CustomerTabs tab={tab} division={division} window={window} filters={filters} onOpen={setOpenId} />
        )}
      </div>
      {openId && (
        <CustomerDrawer division={division} window={window} filters={filters} customerId={openId} onClose={() => setOpenId(null)} />
      )}
    </div>
  )
}

export default function CustomerLifespanPage() {
  return (
    <ReportGuard reportKey="customer-lifespan">
      <Suspense
        fallback={
          <div className="flex h-[60vh] items-center justify-center text-[#6B7280]">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        }
      >
        <LifespanContent />
      </Suspense>
    </ReportGuard>
  )
}
