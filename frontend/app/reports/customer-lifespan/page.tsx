"use client"

import { Suspense, useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Hourglass, Loader2 } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import { WINDOWS, useCustomers, type Division, type Window } from "@/lib/customer-lifespan-api"
import { CohortsPanel } from "./CohortsPanel"
import { CustomerDrawer } from "./CustomerDrawer"
import { CustomerFilters, EMPTY_FILTERS, applyFilters, type Filters } from "./CustomerFilters"
import { CustomersPanel } from "./CustomersPanel"
import { DataSourcesBar } from "./DataSourcesBar"
import { KpiStrip } from "./KpiStrip"
import { LifespanPanel } from "./LifespanPanel"
import { TimelinePanel } from "./TimelinePanel"
import { TrendPanel } from "./TrendPanel"
import { Card, ErrorBox, Loading, Segmented } from "./ui"

const TABS = [
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

function pick<T extends string | number>(raw: string | null, allowed: readonly { k: T }[], fallback: T): T {
  const hit = allowed.find((o) => String(o.k) === raw)
  return hit ? hit.k : fallback
}

/** Customers + Timeline share one list and one set of filters. */
function CustomerTabs({ tab, division, window, onOpen }: {
  tab: "customers" | "timeline"
  division: Division
  window: Window
  onOpen: (id: string) => void
}) {
  const { data, error, isLoading } = useCustomers(division, window)
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const rows = useMemo(() => data?.data ?? [], [data])
  const shown = useMemo(() => applyFilters(rows, filters), [rows, filters])
  const years = useMemo(() => Array.from(new Set(rows.map((r) => r.cohort_year))).sort(), [rows])
  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) return <Loading />
  return (
    <Card>
      <div className="mb-3">
        <CustomerFilters value={filters} onChange={setFilters} years={years} shown={shown.length} total={rows.length} />
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
  const tab = pick<TabKey>(params.get("tab"), TABS, "trends")
  const division = pick<Division>(params.get("division"), DIVISIONS, "all")
  const window = pick<Window>(params.get("window"), WINDOW_OPTIONS, 90)
  const [openId, setOpenId] = useState<string | null>(null)
  const { data: customers } = useCustomers(division, window)

  const setParam = useCallback(
    (key: string, value: string, fallback: string) => {
      const next = new URLSearchParams(params.toString())
      if (value === fallback) next.delete(key)
      else next.set(key, value)
      const qs = next.toString()
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    },
    [params, pathname, router],
  )

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <div className="flex flex-wrap items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link href="/" className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]">
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <Hourglass className="h-4 w-4 text-[#1B3A5C]" />
        <h1 className="text-sm font-semibold text-[#1B3A5C]">Customer Lifespan</h1>
        <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-xs text-[#1D4ED8]">TMS · since 2016</span>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <Segmented label="Division" value={division} options={DIVISIONS} onChange={(v) => setParam("division", v, "all")} />
          <Segmented label="Lost after" value={window} options={WINDOW_OPTIONS} onChange={(v) => setParam("window", String(v), "90")} />
        </div>
      </div>
      <div className="mx-auto w-full max-w-[1600px] space-y-4 px-6 py-4">
        <DataSourcesBar asOf={customers?.meta.as_of} />
        <KpiStrip division={division} window={window} />
        <div className="flex w-fit flex-wrap rounded-lg border border-[#E5E7EB] bg-white text-xs">
          {TABS.map((t) => (
            <button
              key={t.k}
              onClick={() => setParam("tab", t.k, "trends")}
              className={`px-4 py-2 first:rounded-l-lg last:rounded-r-lg ${
                tab === t.k ? "bg-[#1B3A5C] font-semibold text-white" : "text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        {tab === "trends" && <TrendPanel division={division} window={window} />}
        {tab === "cohorts" && <CohortsPanel division={division} window={window} />}
        {tab === "lifespan" && <LifespanPanel division={division} window={window} />}
        {(tab === "customers" || tab === "timeline") && (
          <CustomerTabs tab={tab} division={division} window={window} onOpen={setOpenId} />
        )}
      </div>
      {openId && (
        <CustomerDrawer division={division} window={window} customerId={openId} onClose={() => setOpenId(null)} />
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
