"use client"

import { Suspense, useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import {
  ArrowLeft,
  DollarSign,
  Loader2,
  Percent,
  TrendingDown,
  Truck,
} from "lucide-react"
import {
  useLossesFilters,
  useLossesFreshness,
  useLossesSummary,
  type LossesFilters,
  type LossesRange,
} from "@/lib/losses-lanes-api"
import { LossesErrorBanner } from "./ErrorBanner"
import { ReportGuard } from "@/components/ReportGuard"
import { WorstLanes } from "./tabs/WorstLanes"
import { WorstCustomers } from "./tabs/WorstCustomers"
import { TopCombo } from "./tabs/TopCombo"
import { Trends } from "./tabs/Trends"
import { OrderDetails } from "./tabs/OrderDetails"
import { WeeklyMovers } from "./tabs/WeeklyMovers"
import { LaneTrendModal } from "./LaneTrendModal"

const YEAR_START = "2026-01-01"
const YEAR_END = "2026-12-31"

const ALL_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW"] as const
const CORP_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"]
const DFW_TEAMS = ["TEAM-DFW"]

type TabKey =
  | "lanes"
  | "customers"
  | "top"
  | "trends"
  | "movers"
  | "orders"

const TABS: { key: TabKey; label: string }[] = [
  { key: "lanes", label: "Worst Margins by Lane" },
  { key: "customers", label: "Worst Margins by Customer" },
  { key: "top", label: "Top 10 Combo" },
  { key: "trends", label: "Trends" },
  { key: "movers", label: "Weekly Movers" },
  { key: "orders", label: "Order Details" },
]

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`
}

function monthStartIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`
}

function clampToYear(iso: string) {
  if (iso < YEAR_START) return YEAR_START
  if (iso > YEAR_END) return YEAR_END
  return iso
}

const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const COUNT = new Intl.NumberFormat("en-US")
const PCT2 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
})

const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))
const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT.format(Number(v))
const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT2.format(Number(v))}%`

function fmtTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}

function LossesContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  // Read all URL state ------------------------------------------------------
  const activeTab = (searchParams.get("tab") as TabKey) || "lanes"
  const range = (searchParams.get("range") as LossesRange) || "mtd"
  const startDate = searchParams.get("s") || monthStartIso()
  const endDate = searchParams.get("e") || clampToYear(todayIso())
  const teamsParam = searchParams.get("teams")
  const teams = useMemo<string[]>(() => {
    if (teamsParam === null) return [...ALL_TEAMS]
    if (teamsParam === "") return []
    return teamsParam.split(",").filter((t) => (ALL_TEAMS as readonly string[]).includes(t))
  }, [teamsParam])
  const customer = searchParams.get("customer") || ""
  const orderLane = searchParams.get("lane") || undefined
  const t1Pct = Number(searchParams.get("t1") ?? "15")
  const t2Pct = Number(searchParams.get("t2") ?? "18")
  const t3Pct = Number(searchParams.get("t3") ?? "20")
  const thresholds: [number, number, number] = [
    (Number.isFinite(t1Pct) ? t1Pct : 15) / 100,
    (Number.isFinite(t2Pct) ? t2Pct : 18) / 100,
    (Number.isFinite(t3Pct) ? t3Pct : 20) / 100,
  ]

  // Write URL state — only non-default values are kept in the URL so shared
  // links are short and scannable. `null` deletes the key.
  const updateUrl = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      const next = new URLSearchParams(searchParams.toString())
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === undefined) next.delete(k)
        else next.set(k, v)
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [searchParams, router, pathname],
  )

  const setTab = (tab: TabKey) => updateUrl({ tab: tab === "lanes" ? null : tab })
  const setRange = (r: LossesRange) => updateUrl({ range: r === "mtd" ? null : r })
  const setStartDate = (d: string) => updateUrl({ s: d })
  const setEndDate = (d: string) => updateUrl({ e: d })
  const setCustomer = (c: string) => updateUrl({ customer: c || null })
  const setOrderLane = (lane: string | undefined) => updateUrl({ lane: lane || null })
  const setTeams = (next: string[]) => {
    // Default "all" => URL value omitted; explicit empty => URL value = ""
    if (next.length === ALL_TEAMS.length) {
      updateUrl({ teams: null })
    } else {
      updateUrl({ teams: next.join(",") })
    }
  }
  const setThresholdPct = (idx: 0 | 1 | 2, pct: number) => {
    const keys = ["t1", "t2", "t3"] as const
    const defaults = [15, 18, 20]
    updateUrl({
      [keys[idx]]:
        !Number.isFinite(pct) || pct === defaults[idx] ? null : String(pct),
    })
  }

  // Non-URL state (transient modal)
  const [trendLane, setTrendLane] = useState<string | undefined>(undefined)

  const toggleTeam = (t: string) => {
    setTeams(teams.includes(t) ? teams.filter((x) => x !== t) : [...teams, t])
  }
  const allTeamsSelected = teams.length === ALL_TEAMS.length
  const onlyCorp =
    teams.length === CORP_TEAMS.length &&
    teams.every((t) => CORP_TEAMS.includes(t))
  const onlyDfw =
    teams.length === DFW_TEAMS.length &&
    teams.every((t) => DFW_TEAMS.includes(t))

  const { data: filterRes, isLoading: loadingFilters } = useLossesFilters()
  const filterOptions = filterRes?.data

  const filters: LossesFilters = useMemo(
    () => ({
      range,
      startDate: range === "custom" ? clampToYear(startDate) : undefined,
      endDate: range === "custom" ? clampToYear(endDate) : undefined,
      teams,
      customer: customer || undefined,
    }),
    [range, startDate, endDate, teams, customer],
  )

  const { data: summaryRes, isLoading: loadingSummary, error: summaryErr } =
    useLossesSummary(filters)
  const s = summaryRes?.data
  const { data: freshnessRes } = useLossesFreshness()
  const fr = freshnessRes?.data

  const [customerInput, setCustomerInput] = useState<string>("")
  const customerSuggestions = useMemo(() => {
    const q = customerInput.trim().toLowerCase()
    if (!q || !filterOptions?.customers) return []
    return filterOptions.customers.filter((c) => c.toLowerCase().includes(q)).slice(0, 8)
  }, [customerInput, filterOptions])

  const windowLabel = s?.window
    ? `${s.window.start} → ${s.window.end}`
    : range === "custom"
      ? `${clampToYear(startDate)} → ${clampToYear(endDate)}`
      : range.replace("_", " ").toUpperCase()

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
          <TrendingDown className="h-4 w-4 text-[#DC2626]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">Top Losses Lanes</h1>
          <span className="rounded-full bg-[#FEE2E2] px-2 py-0.5 text-xs text-[#991B1B]">
            margin &lt; 0
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          <span>
            {windowLabel}
            {" · "}
            Teams: {allTeamsSelected ? "All" : teams.join(", ") || "None"}
            {" · "}
            Customer: {customer || "All"}
          </span>
          {fr?.last_updated && (
            <span
              className="rounded-full bg-[#F3F4F6] px-2 py-0.5 text-[10px] text-[#374151]"
              title={`Source: mcleod_gld_budget_report_v4 · ${fr.rows_in_scope.toLocaleString()} rows in scope`}
            >
              Data refreshed: {fmtTimestamp(fr.last_updated)}
            </span>
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Range
            </label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {[
                { k: "mtd" as const, label: "MTD" },
                { k: "last_month" as const, label: "Last Month" },
                { k: "ytd" as const, label: "This Year" },
                { k: "custom" as const, label: "Custom" },
              ].map((opt) => (
                <button
                  key={opt.k}
                  onClick={() => setRange(opt.k)}
                  className={`px-3 py-1.5 ${
                    range === opt.k
                      ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                      : "text-[#6B7280] hover:text-[#111827]"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {range === "custom" && (
              <div className="flex items-center gap-1 text-xs">
                <input
                  type="date"
                  min={YEAR_START}
                  max={YEAR_END}
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
                <span className="text-[#6B7280]">→</span>
                <input
                  type="date"
                  min={YEAR_START}
                  max={YEAR_END}
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Teams
            </label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              <TeamModeBtn
                label="All"
                active={allTeamsSelected}
                onClick={() => setTeams([...ALL_TEAMS])}
              />
              <TeamModeBtn
                label="CORP"
                active={onlyCorp}
                onClick={() => setTeams(CORP_TEAMS)}
              />
              <TeamModeBtn
                label="DFW"
                active={onlyDfw}
                onClick={() => setTeams(DFW_TEAMS)}
              />
            </div>
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

          <div className="relative flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Customer
            </label>
            <input
              type="text"
              placeholder={loadingFilters ? "Loading…" : customer || "All customers"}
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

          {loadingFilters && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
        </div>

        {/* Tab switcher */}
        <div className="mx-auto flex w-full max-w-[1920px] gap-1 overflow-x-auto border-t border-[#E5E7EB] px-6">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setTab(tab.key)}
              className={`border-b-2 px-4 py-2 text-xs font-semibold transition-colors ${
                activeTab === tab.key
                  ? "border-[#1B3A5C] text-[#1B3A5C]"
                  : "border-transparent text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* KPI cards */}
      <div className="mx-auto w-full max-w-[1920px] px-6 pt-4">
        <LossesErrorBanner errors={[summaryErr]} label="Summary" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <KpiCard
            icon={<Truck className="h-4 w-4" />}
            label="# Loads"
            value={loadingSummary ? "—" : fmtCount(s?.loads)}
            accent="text-[#DC2626]"
          />
          <KpiCard
            icon={<DollarSign className="h-4 w-4" />}
            label="Revenue"
            value={loadingSummary ? "—" : fmtUsd(s?.revenue)}
            accent="text-[#1B3A5C]"
          />
          <KpiCard
            icon={<TrendingDown className="h-4 w-4" />}
            label="$ Profit"
            value={loadingSummary ? "—" : fmtUsd(s?.profit)}
            accent="text-[#B45309]"
          />
          <KpiCard
            icon={<Percent className="h-4 w-4" />}
            label="% Margin"
            value={loadingSummary ? "—" : fmtPct(s?.margin_pct)}
            accent="text-[#7C3AED]"
          />
        </div>
      </div>

      {/* Tab body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 px-6 py-6">
        {activeTab === "lanes" && (
          <WorstLanes
            filters={filters}
            thresholds={thresholds}
            thresholdsPct={[t1Pct, t2Pct, t3Pct]}
            onChangeThresholdPct={setThresholdPct}
            onDrillOrders={(lane) => {
              setOrderLane(lane)
              setTab("orders")
            }}
            onShowTrend={(lane) => setTrendLane(lane)}
          />
        )}
        {activeTab === "customers" && <WorstCustomers filters={filters} />}
        {activeTab === "top" && (
          <TopCombo
            filters={filters}
            onDrillOrders={(lane) => {
              setOrderLane(lane)
              setTab("orders")
            }}
            onShowTrend={(lane) => setTrendLane(lane)}
          />
        )}
        {activeTab === "trends" && <Trends filters={filters} />}
        {activeTab === "movers" && (
          <WeeklyMovers
            teams={teams}
            customer={customer || undefined}
            onShowTrend={(lane) => setTrendLane(lane)}
          />
        )}
        {activeTab === "orders" && (
          <OrderDetails
            filters={filters}
            lane={orderLane}
            onClearLane={() => setOrderLane(undefined)}
          />
        )}
      </div>

      {/* Lane-trend modal */}
      {trendLane && (
        <LaneTrendModal
          lane={trendLane}
          teams={teams}
          customer={customer || undefined}
          onClose={() => setTrendLane(undefined)}
        />
      )}
    </div>
  )
}

function KpiCard({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode
  label: string
  value: string
  accent: string
}) {
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
          {label}
        </div>
        <div className={accent}>{icon}</div>
      </div>
      <div className={`mt-2 text-2xl font-semibold ${accent}`}>{value}</div>
    </div>
  )
}

function TeamModeBtn({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 ${
        active
          ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
          : "text-[#6B7280] hover:text-[#111827]"
      }`}
    >
      {label}
    </button>
  )
}

export default function LossesLanesPage() {
  return (
    <ReportGuard reportKey="losses-lanes">
      <Suspense
        fallback={
          <div className="flex min-h-[calc(100vh-64px)] items-center justify-center bg-[#F9FAFB]">
            <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
          </div>
        }
      >
        <LossesContent />
      </Suspense>
    </ReportGuard>
  )
}
