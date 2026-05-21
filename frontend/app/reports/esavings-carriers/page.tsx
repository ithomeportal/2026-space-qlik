"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import {
  ArrowLeft,
  ChevronDown,
  Loader2,
  PiggyBank,
  TrendingDown,
  TrendingUp,
  Truck,
  X,
} from "lucide-react"
import {
  useSavingsByCustomer,
  useSavingsByTeam,
  useSavingsCustomers,
  useSavingsLaneRates,
  useSavingsLanes,
  useSavingsMonthlyTotals,
  useSavingsMonths,
  useSavingsSummary,
  type SavingsDivision,
  type SavingsLaneRate,
  type SavingsScopeFilters,
} from "@/lib/api"
import { useDebounce } from "@/lib/use-debounce"
import { TeamSummaryTable } from "./TeamSummaryTable"
import { MonthlyTotalsChart } from "./MonthlyTotalsChart"
import { ReportGuard } from "@/components/ReportGuard"

const CORP_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"] as const
const DFW_TEAMS = ["TEAM-DFW"] as const

type FilterMode = "include" | "exclude"

// Business target: $55,000 savings per division per month (CORP, DFW).
// When no division filter is applied, we show the combined target so the
// progress bar reflects "both divisions together".
const MONTHLY_SAVINGS_GOAL_PER_DIVISION = 55_000

const CURRENCY = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const COUNT = new Intl.NumberFormat("en-US")

function fmtCurrency(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—"
  return CURRENCY.format(Number(v))
}

function fmtCount(v: number | null | undefined) {
  if (v === null || v === undefined) return "—"
  return COUNT.format(Number(v))
}

function fmtMonth(iso: string | null | undefined) {
  if (!iso) return "—"
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`)
  return d.toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  })
}

/**
 * Display label for the source-table `base_month` value.
 *  - `'Q1-2026'` → `'Q1-26'`        (Bruno R-2)
 *  - `'2025-07'` → `'2025-07'`      (untouched)
 *  - `null` / `'None'` → `'—'`
 */
function fmtBaseMonth(base: string | null | undefined): string {
  if (!base || base === "None") return "—"
  const m = base.match(/^(Q[1-4])-(\d{4})$/)
  if (m) return `${m[1]}-${m[2].slice(2)}`
  return base
}

export default function ESavingsFromCarriersPage() {
  return (
    <ReportGuard reportKey="esavings-carriers">
      <ESavingsFromCarriersContent />
    </ReportGuard>
  )
}

function ESavingsFromCarriersContent() {
  const [month, setMonth] = useState<string | undefined>(undefined)
  const [origin, setOrigin] = useState("")
  const [dest, setDest] = useState("")
  const [division, setDivision] = useState<SavingsDivision | undefined>(undefined)
  // Multi-select scope filters (Bruno R-2). The legacy single-value `customer_id`
  // / `team` query params remain supported server-side; the UI no longer needs
  // them now that everything goes through the picker.
  const [teamIds, setTeamIds] = useState<string[]>([])
  const [teamMode, setTeamMode] = useState<FilterMode>("include")
  const [customerIds, setCustomerIds] = useState<string[]>([])
  const [customerMode, setCustomerMode] = useState<FilterMode>("include")
  const [sort, setSort] = useState("variance_desc")
  const [page, setPage] = useState(1)
  const limit = 100

  const { data: monthsRes, isLoading: loadingMonths } = useSavingsMonths()
  const months = monthsRes?.data ?? []

  // Default to the current calendar month when it has data; otherwise the
  // latest month returned by the API.
  const currentMonthIso = useMemo(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`
  }, [])
  const effectiveMonth =
    month ??
    months.find((m) => m.month_date === currentMonthIso)?.month_date ??
    months[0]?.month_date

  // Debounce Origin/Destination so every keystroke doesn't refire the 5 queries.
  const debouncedOrigin = useDebounce(origin.trim(), 300)
  const debouncedDest = useDebounce(dest.trim(), 300)

  const teamOptions = useMemo(() => {
    const ids = division === "CORP"
      ? CORP_TEAMS
      : division === "DFW"
        ? DFW_TEAMS
        : [...CORP_TEAMS, ...DFW_TEAMS]
    return ids.map((id) => ({ id, label: id }))
  }, [division])

  const { data: customersRes, isFetching: loadingCustomers } =
    useSavingsCustomers(division)
  const customerOptions = useMemo(
    () =>
      (customersRes?.data ?? []).map((c) => ({
        id: c.customer_id,
        label: c.customer_name || c.customer_id,
        secondary: c.customer_id,
      })),
    [customersRes],
  )

  const scope = useMemo<SavingsScopeFilters>(
    () => ({
      teamIds: teamMode === "include" ? teamIds : undefined,
      excludeTeamIds: teamMode === "exclude" ? teamIds : undefined,
      customerIds: customerMode === "include" ? customerIds : undefined,
      excludeCustomerIds: customerMode === "exclude" ? customerIds : undefined,
    }),
    [teamIds, teamMode, customerIds, customerMode],
  )

  const { data: summaryRes, isLoading: loadingSummary } = useSavingsSummary(
    effectiveMonth,
    undefined,
    division,
    undefined,
    debouncedOrigin || undefined,
    debouncedDest || undefined,
    scope,
  )
  const summary = summaryRes?.data
  const { data: byCustomerRes } = useSavingsByCustomer(
    effectiveMonth,
    25,
    division,
    undefined,
    debouncedOrigin || undefined,
    debouncedDest || undefined,
    scope,
  )
  const customers = byCustomerRes?.data ?? []

  const { data: byTeamRes, isLoading: loadingByTeam } = useSavingsByTeam(
    effectiveMonth,
    undefined,
    division,
    undefined,
    debouncedOrigin || undefined,
    debouncedDest || undefined,
    scope,
  )
  const teamRows = byTeamRes?.data ?? []

  const { data: monthlyRes, isLoading: loadingMonthly } = useSavingsMonthlyTotals(
    undefined,
    division,
    undefined,
    9,
    debouncedOrigin || undefined,
    debouncedDest || undefined,
    scope,
  )
  const monthlyRows = monthlyRes?.data ?? []

  const lanesFilters = useMemo(
    () => ({
      month: effectiveMonth,
      origin: debouncedOrigin || undefined,
      dest: debouncedDest || undefined,
      sort,
      page,
      limit,
      division,
      scope,
    }),
    [
      effectiveMonth,
      debouncedOrigin,
      debouncedDest,
      sort,
      page,
      division,
      scope,
    ],
  )
  const { data: lanesRes, isLoading: loadingLanes } = useSavingsLanes(lanesFilters)
  const lanes = lanesRes?.data ?? []
  const totalLanes = lanesRes?.meta?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(totalLanes / limit))

  // SONAR + 123LB monthly benchmark rates for the same page of lanes.
  // First call against a cold lane is slow (external APIs); subsequent loads
  // of the same month are instant (cache hit on lane_market_rates).
  const { data: rateRes, isFetching: loadingRates } = useSavingsLaneRates(lanesFilters)
  const rateMap = rateRes?.data ?? {}

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Header bar */}
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
          <PiggyBank className="h-4 w-4 text-[#059669]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">
            eSavings from Carriers
          </h1>
          <span className="rounded-full bg-[#F3F4F6] px-2 py-0.5 text-xs text-[#6B7280]">
            Operations
          </span>
        </div>
        <div className="ml-auto text-xs text-[#6B7280]">
          Base: {fmtBaseMonth(summary?.base_month)}
          {" · "}
          Month: {fmtMonth(effectiveMonth)}
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-6 px-6 py-6">
        {/* Month / Division / Corp Team selectors */}
        <section className="flex flex-wrap items-center gap-3">
          <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
            Month
          </label>
          {loadingMonths ? (
            <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />
          ) : (
            <select
              value={effectiveMonth ?? ""}
              onChange={(e) => {
                setMonth(e.target.value || undefined)
                setPage(1)
              }}
              className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-sm text-[#111827] shadow-sm focus:border-[#1B3A5C] focus:outline-none"
            >
              {months.map((m) => (
                <option key={m.month_date} value={m.month_date}>
                  {fmtMonth(m.month_date)}
                  {m.base_month ? ` — base ${m.base_month}` : ""}
                </option>
              ))}
            </select>
          )}

          <span className="h-5 w-px bg-[#E5E7EB]" aria-hidden />

          <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
            Division
          </label>
          <select
            value={division ?? ""}
            onChange={(e) => {
              const next = (e.target.value || undefined) as SavingsDivision | undefined
              setDivision(next)
              // Drop team selections that no longer fit the new division universe.
              if (next === "CORP") {
                setTeamIds((prev) => prev.filter((t) => CORP_TEAMS.includes(t as (typeof CORP_TEAMS)[number])))
              } else if (next === "DFW") {
                setTeamIds((prev) => prev.filter((t) => DFW_TEAMS.includes(t as (typeof DFW_TEAMS)[number])))
              }
              setPage(1)
            }}
            className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-sm text-[#111827] shadow-sm focus:border-[#1B3A5C] focus:outline-none"
          >
            <option value="">All</option>
            <option value="CORP">CORP</option>
            <option value="DFW">DFW</option>
          </select>

          <MultiSelectChips
            label="Team"
            options={teamOptions}
            selected={teamIds}
            mode={teamMode}
            onSelectionChange={(next) => {
              setTeamIds(next)
              setPage(1)
            }}
            onModeChange={(next) => {
              setTeamMode(next)
              setPage(1)
            }}
            placeholder="All teams"
            width={170}
          />

          <MultiSelectChips
            label="Customer"
            options={customerOptions}
            selected={customerIds}
            mode={customerMode}
            onSelectionChange={(next) => {
              setCustomerIds(next)
              setPage(1)
            }}
            onModeChange={(next) => {
              setCustomerMode(next)
              setPage(1)
            }}
            placeholder={loadingCustomers ? "Loading…" : "All customers"}
            searchable
            width={260}
          />

          <span className="h-5 w-px bg-[#E5E7EB]" aria-hidden />

          <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
            Origin
          </label>
          <input
            value={origin}
            onChange={(e) => {
              setOrigin(e.target.value)
              setPage(1)
            }}
            placeholder="e.g. Waco, TX"
            className="w-48 rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-sm text-[#111827] shadow-sm focus:border-[#1B3A5C] focus:outline-none"
          />

          <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
            Destination
          </label>
          <input
            value={dest}
            onChange={(e) => {
              setDest(e.target.value)
              setPage(1)
            }}
            placeholder="e.g. Laredo, TX"
            className="w-48 rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-sm text-[#111827] shadow-sm focus:border-[#1B3A5C] focus:outline-none"
          />

          {(origin || dest) && (
            <button
              onClick={() => {
                setOrigin("")
                setDest("")
                setPage(1)
              }}
              className="rounded-full border border-[#E5E7EB] bg-white px-3 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
            >
              Clear lanes
            </button>
          )}
        </section>

        {/* 4 main KPIs */}
        <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <KpiCard
            label="Volume (loads)"
            value={fmtCount(summary?.total_loads)}
            icon={<Truck className="h-5 w-5" />}
            tone="neutral"
            loading={loadingSummary}
          />
          <KpiCard
            label="Total Savings"
            value={fmtCurrency(summary?.total_savings)}
            icon={<TrendingUp className="h-5 w-5" />}
            tone="positive"
            loading={loadingSummary}
          />
          <KpiCard
            label="Total Overpay"
            value={fmtCurrency(summary?.total_overpay)}
            icon={<TrendingDown className="h-5 w-5" />}
            tone="negative"
            loading={loadingSummary}
          />
          <KpiCard
            label="Net Variance"
            value={fmtCurrency(summary?.net_variance)}
            icon={<PiggyBank className="h-5 w-5" />}
            tone={
              (summary?.net_variance ?? 0) >= 0 ? "positive" : "negative"
            }
            loading={loadingSummary}
            goal={{
              amount:
                division === "CORP" || division === "DFW"
                  ? MONTHLY_SAVINGS_GOAL_PER_DIVISION
                  : MONTHLY_SAVINGS_GOAL_PER_DIVISION * 2,
              actual: Number(summary?.net_variance ?? 0),
              scopeLabel:
                division === "CORP"
                  ? "CORP goal"
                  : division === "DFW"
                    ? "DFW goal"
                    : "CORP + DFW goal",
            }}
          />
        </section>

        {/* Secondary KPIs */}
        <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <MiniKpi label="High-Vol Lanes (≥8)" value={fmtCount(summary?.high_vol_lanes)} />
          <MiniKpi label="HV + Savings" value={fmtCount(summary?.high_vol_savings_lanes)} />
          <MiniKpi label="Low-Vol Lanes (1–7)" value={fmtCount(summary?.low_vol_lanes)} />
          <MiniKpi label="LV + Savings" value={fmtCount(summary?.low_vol_savings_lanes)} />
        </section>

        {/* Team Summary (~35%) + Monthly trend (~65%) */}
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
          <section className="xl:col-span-4">
            <TeamSummaryTable rows={teamRows} loading={loadingByTeam} />
          </section>
          <section className="xl:col-span-8">
            <MonthlyTotalsChart rows={monthlyRows} loading={loadingMonthly} />
          </section>
        </div>

        {/* Customer summary + Lane detail */}
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
          <section className="xl:col-span-4">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-[#6B7280]">
              Top Customers
            </h2>
            <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
              <table className="w-full text-sm">
                <thead className="bg-[#F9FAFB] text-xs uppercase tracking-wider text-[#6B7280]">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Customer</th>
                    <th className="px-3 py-2 text-right font-medium">Loads</th>
                    <th className="px-3 py-2 text-right font-medium">Net</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F3F4F6]">
                  {customers.length === 0 && (
                    <tr>
                      <td
                        colSpan={3}
                        className="px-3 py-6 text-center text-xs text-[#9CA3AF]"
                      >
                        No customers for this month
                      </td>
                    </tr>
                  )}
                  {customers.map((c) => {
                    const isActive =
                      customerMode === "include" && customerIds.includes(c.customer_id)
                    return (
                    <tr
                      key={c.customer_id}
                      onClick={() => {
                        setCustomerMode("include")
                        setCustomerIds([c.customer_id])
                        setPage(1)
                      }}
                      className={`cursor-pointer transition-colors ${
                        isActive
                          ? "bg-[#EFF6FF]"
                          : "hover:bg-[#F9FAFB]"
                      }`}
                    >
                      <td className="px-3 py-2">
                        <div className="font-medium text-[#111827]">
                          {c.customer_name}
                        </div>
                        <div className="text-xs text-[#6B7280]">
                          {c.customer_id}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {fmtCount(c.loads)}
                      </td>
                      <td
                        className={`px-3 py-2 text-right tabular-nums font-medium ${
                          Number(c.net_variance) >= 0
                            ? "text-[#059669]"
                            : "text-[#DC2626]"
                        }`}
                      >
                        {fmtCurrency(c.net_variance)}
                      </td>
                    </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="xl:col-span-8">
            <div className="mb-2 flex items-end justify-between gap-3">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-[#6B7280]">
                Lanes ({fmtCount(totalLanes)})
              </h2>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={sort}
                  onChange={(e) => {
                    setSort(e.target.value)
                    setPage(1)
                  }}
                  className="rounded-lg border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs focus:border-[#1B3A5C] focus:outline-none"
                >
                  <option value="variance_desc">Biggest savings</option>
                  <option value="variance_asc">Biggest loss</option>
                  <option value="loads_desc">Most loads</option>
                  <option value="cost_desc">Highest cost</option>
                  <option value="customer">Customer (A–Z)</option>
                </select>
              </div>
            </div>

            <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-[#F9FAFB] text-xs uppercase tracking-wider text-[#6B7280]">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Customer</th>
                      <th className="px-3 py-2 text-left font-medium">Origin</th>
                      <th className="px-3 py-2 text-left font-medium">Destination</th>
                      <th className="px-3 py-2 text-right font-medium">Loads</th>
                      <th className="px-3 py-2 text-right font-medium">Avg $</th>
                      <th className="px-3 py-2 text-right font-medium">Base $</th>
                      <th className="px-3 py-2 text-right font-medium">Cost</th>
                      <th className="px-3 py-2 text-right font-medium">Variance</th>
                      <th
                        className="px-3 py-2 text-right font-medium"
                        title="SONAR (FreightWaves) TRAC monthly avg for this lane"
                      >
                        SONAR $
                      </th>
                      <th
                        className="px-3 py-2 text-right font-medium"
                        title="123LoadBoard rate-history monthly avg for this lane"
                      >
                        123LB $
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F3F4F6]">
                    {loadingLanes && lanes.length === 0 && (
                      <tr>
                        <td colSpan={10} className="px-3 py-6 text-center">
                          <Loader2 className="mx-auto h-5 w-5 animate-spin text-[#6B7280]" />
                        </td>
                      </tr>
                    )}
                    {!loadingLanes && lanes.length === 0 && (
                      <tr>
                        <td
                          colSpan={10}
                          className="px-3 py-6 text-center text-xs text-[#9CA3AF]"
                        >
                          No lanes match the current filters
                        </td>
                      </tr>
                    )}
                    {lanes.map((lane) => {
                      const rates =
                        rateMap[`${lane.customer_id}|${lane.origin_name}|${lane.dest_name}`]
                      return (
                        <tr
                          key={`${lane.customer_id}-${lane.origin_name}-${lane.dest_name}-${lane.month_date}`}
                          className="hover:bg-[#F9FAFB]"
                        >
                          <td className="px-3 py-2">
                            <div className="font-medium text-[#111827]">
                              {lane.customer_name}
                            </div>
                            <div className="text-xs text-[#6B7280]">
                              {lane.customer_id}
                            </div>
                          </td>
                          <td className="px-3 py-2 text-[#374151]">
                            {lane.origin_name}
                          </td>
                          <td className="px-3 py-2 text-[#374151]">
                            {lane.dest_name}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {fmtCount(lane.number_monthly_loads)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                            {fmtCurrency(lane.avg_monthly_usd)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-[#6B7280]">
                            <div className="flex flex-col items-end leading-tight">
                              <span>{fmtCurrency(lane.base_lane)}</span>
                              <BaseMonthChip
                                baseMonth={lane.base_month}
                                monthDate={lane.month_date}
                              />
                            </div>
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                            {fmtCurrency(lane.cost_monthly_usd)}
                          </td>
                          <td
                            className={`px-3 py-2 text-right tabular-nums font-semibold ${
                              Number(lane.variance) >= 0
                                ? "text-[#059669]"
                                : "text-[#DC2626]"
                            }`}
                          >
                            {fmtCurrency(lane.variance)}
                          </td>
                          <RateCell
                            rate={rates?.sonar ?? null}
                            skipReason={rates?.skip_reason}
                            loading={loadingRates && !rates}
                          />
                          <RateCell
                            rate={rates?.lb123 ?? null}
                            skipReason={rates?.skip_reason}
                            loading={loadingRates && !rates}
                          />
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="flex items-center justify-between border-t border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2 text-xs text-[#6B7280]">
                <div>
                  Page {page} of {pageCount}
                </div>
                <div className="flex gap-1">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    className="rounded-md border border-[#E5E7EB] bg-white px-3 py-1 disabled:opacity-40 hover:bg-[#F3F4F6]"
                  >
                    Prev
                  </button>
                  <button
                    disabled={page >= pageCount}
                    onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                    className="rounded-md border border-[#E5E7EB] bg-white px-3 py-1 disabled:opacity-40 hover:bg-[#F3F4F6]"
                  >
                    Next
                  </button>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

interface KpiCardProps {
  label: string
  value: string
  icon: React.ReactNode
  tone: "neutral" | "positive" | "negative"
  loading?: boolean
  goal?: {
    amount: number
    actual: number
    scopeLabel: string
  }
}

function KpiCard({ label, value, icon, tone, loading, goal }: KpiCardProps) {
  const toneClasses = {
    neutral: "bg-gradient-to-br from-[#1B3A5C] to-[#2563EB]",
    positive: "bg-gradient-to-br from-[#065F46] to-[#10B981]",
    negative: "bg-gradient-to-br from-[#991B1B] to-[#EF4444]",
  }[tone]

  const rawPct = goal && goal.amount > 0 ? (goal.actual / goal.amount) * 100 : 0
  const barPct = Math.max(0, Math.min(100, rawPct))
  const barColor =
    rawPct >= 100
      ? "bg-[#059669]"
      : rawPct >= 50
        ? "bg-[#2563EB]"
        : "bg-[#F59E0B]"

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
          {label}
        </div>
        <div
          className={`flex h-8 w-8 items-center justify-center rounded-lg text-white ${toneClasses}`}
        >
          {icon}
        </div>
      </div>
      <div className="mt-3 text-2xl font-bold tabular-nums text-[#111827]">
        {loading ? (
          <Loader2 className="h-6 w-6 animate-spin text-[#9CA3AF]" />
        ) : (
          value
        )}
      </div>
      {goal && !loading && (
        <div className="mt-3">
          <div className="flex items-baseline justify-between gap-2 text-xs">
            <span className="font-medium text-[#374151] tabular-nums">
              {Math.round(rawPct)}%
              <span className="ml-1 font-normal text-[#6B7280]">
                of {fmtCurrency(goal.amount)}
              </span>
            </span>
            <span className="text-[10px] uppercase tracking-wider text-[#9CA3AF]">
              {goal.scopeLabel}
            </span>
          </div>
          <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-[#F3F4F6]">
            <div
              className={`h-full rounded-full transition-[width] duration-500 ${barColor}`}
              style={{ width: `${barPct}%` }}
            />
          </div>
        </div>
      )}
    </div>
  )
}

// Stale-base detector: any row whose displayed base predates the current
// quarter's reference period (e.g. Apr–Dec 2026 row showing a 2025-MM base
// instead of `Q1-2026`). Should be empty after the n8n zero-base deploy.
function isStaleBase(
  baseMonth: string | null | undefined,
  monthDate: string | null | undefined,
): boolean {
  if (!baseMonth || !monthDate) return false
  if (baseMonth.startsWith("Q") || baseMonth === "None") return false
  const m = monthDate.slice(0, 7)
  if (m >= "2026-04" && baseMonth < "2026-01") return true
  return false
}

function BaseMonthChip({
  baseMonth,
  monthDate,
}: {
  baseMonth: string | null | undefined
  monthDate: string | null | undefined
}) {
  if (!baseMonth || baseMonth === "None") return null
  const stale = isStaleBase(baseMonth, monthDate)
  const className = stale
    ? "mt-0.5 inline-flex items-center gap-1 rounded-sm bg-[#FEE2E2] px-1 py-px text-[10px] font-medium text-[#991B1B]"
    : "mt-0.5 inline-flex items-center rounded-sm bg-[#F3F4F6] px-1 py-px text-[10px] font-medium text-[#6B7280]"
  return (
    <span
      className={className}
      title={
        stale
          ? `Stale base: this Apr–Dec 2026 row is using a ${baseMonth} carrier cost instead of Q1-2026 (no Q1 history)`
          : `Base period applied to this row (source value: ${baseMonth})`
      }
    >
      {stale ? <span aria-hidden="true">●</span> : null}
      {fmtBaseMonth(baseMonth)}
    </span>
  )
}

interface RateCellProps {
  rate: SavingsLaneRate | null
  skipReason?: "non-us" | "unparseable"
  loading: boolean
}

function RateCell({ rate, skipReason, loading }: RateCellProps) {
  if (loading) {
    return (
      <td className="px-3 py-2 text-right text-xs text-[#9CA3AF]">
        <span className="inline-block h-3 w-12 animate-pulse rounded bg-[#F3F4F6]" />
      </td>
    )
  }
  if (skipReason === "non-us") {
    return (
      <td
        className="px-3 py-2 text-right text-xs text-[#9CA3AF]"
        title="Cross-border lane — SONAR/123LB are US-only"
      >
        n/a
      </td>
    )
  }
  if (!rate || rate.avg_rate == null) {
    return (
      <td
        className="px-3 py-2 text-right text-xs text-[#9CA3AF]"
        title="No data returned for this lane and month"
      >
        —
      </td>
    )
  }
  const tooltip = [
    rate.avg_rpm != null ? `RPM ${rate.avg_rpm.toFixed(2)}` : null,
    rate.mileage != null ? `${rate.mileage} mi` : null,
    rate.loads_included != null ? `${rate.loads_included} loads` : null,
  ]
    .filter(Boolean)
    .join(" · ")
  return (
    <td
      className="px-3 py-2 text-right tabular-nums text-[#374151]"
      title={tooltip || undefined}
    >
      {fmtCurrency(rate.avg_rate)}
    </td>
  )
}

function MiniKpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-[#111827]">
        {value}
      </div>
    </div>
  )
}

interface MultiSelectOption {
  id: string
  label: string
  secondary?: string
}

interface MultiSelectChipsProps {
  label: string
  options: MultiSelectOption[]
  selected: string[]
  mode: FilterMode
  onSelectionChange: (next: string[]) => void
  onModeChange: (next: FilterMode) => void
  placeholder?: string
  searchable?: boolean
  width?: number
  disabled?: boolean
}

/**
 * Compact multi-select with an Include / Exclude toggle. Designed to live in
 * the eSavings filter strip; uses only plain React + HTML (no Base UI / cmdk
 * — see CLAUDE.md "Search bar is pure React/HTML").
 *
 * When nothing is selected, the trigger reads "All …" — the backend treats
 * both empty arrays as "no filter" so the include/exclude mode is irrelevant
 * until at least one option is checked.
 */
function MultiSelectChips({
  label,
  options,
  selected,
  mode,
  onSelectionChange,
  onModeChange,
  placeholder,
  searchable,
  width = 200,
  disabled = false,
}: MultiSelectChipsProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [open])

  const showSearch = searchable ?? options.length > 8
  const lowerQuery = query.trim().toLowerCase()
  const filtered = useMemo(() => {
    if (!lowerQuery) return options
    return options.filter((o) => {
      const hay = `${o.label} ${o.secondary ?? ""}`.toLowerCase()
      return hay.includes(lowerQuery)
    })
  }, [options, lowerQuery])

  const selectedSet = useMemo(() => new Set(selected), [selected])
  const summary = selected.length === 0
    ? placeholder ?? `All ${label.toLowerCase()}s`
    : selected.length === 1
      ? options.find((o) => o.id === selected[0])?.label ?? selected[0]
      : `${selected.length} selected`

  const toggle = (id: string) => {
    if (selectedSet.has(id)) {
      onSelectionChange(selected.filter((x) => x !== id))
    } else {
      onSelectionChange([...selected, id])
    }
  }
  const clear = () => {
    onSelectionChange([])
    setQuery("")
  }

  return (
    <div ref={ref} className="relative inline-flex items-center gap-1.5">
      <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </label>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        style={{ width }}
        className={`flex items-center justify-between gap-2 rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-left text-sm text-[#111827] shadow-sm hover:bg-[#F9FAFB] focus:border-[#1B3A5C] focus:outline-none ${
          disabled ? "cursor-not-allowed bg-[#F9FAFB] text-[#9CA3AF]" : ""
        }`}
      >
        <span className="flex min-w-0 items-center gap-2">
          {selected.length > 0 && (
            <span
              className={`shrink-0 rounded-full px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider ${
                mode === "include"
                  ? "bg-[#DBEAFE] text-[#1D4ED8]"
                  : "bg-[#FEE2E2] text-[#991B1B]"
              }`}
            >
              {mode === "include" ? "incl" : "excl"}
            </span>
          )}
          <span className="truncate">{summary}</span>
        </span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[#6B7280]" />
      </button>

      {open && !disabled && (
        <div
          className="absolute left-0 top-full z-30 mt-1 min-w-[260px] rounded-lg border border-[#E5E7EB] bg-white shadow-lg"
          style={{ width: Math.max(width, 260) }}
        >
          <div className="flex items-center justify-between gap-2 border-b border-[#F3F4F6] px-3 py-2">
            <div className="inline-flex rounded-full bg-[#F3F4F6] p-0.5 text-[11px] font-medium">
              <button
                type="button"
                onClick={() => onModeChange("include")}
                className={`rounded-full px-2.5 py-0.5 transition ${
                  mode === "include"
                    ? "bg-[#1D4ED8] text-white shadow-sm"
                    : "text-[#374151] hover:text-[#111827]"
                }`}
              >
                Include
              </button>
              <button
                type="button"
                onClick={() => onModeChange("exclude")}
                className={`rounded-full px-2.5 py-0.5 transition ${
                  mode === "exclude"
                    ? "bg-[#991B1B] text-white shadow-sm"
                    : "text-[#374151] hover:text-[#111827]"
                }`}
              >
                Exclude
              </button>
            </div>
            {selected.length > 0 && (
              <button
                type="button"
                onClick={clear}
                className="flex items-center gap-1 text-[11px] text-[#6B7280] hover:text-[#111827]"
              >
                <X className="h-3 w-3" />
                Clear
              </button>
            )}
          </div>

          {showSearch && (
            <div className="border-b border-[#F3F4F6] px-2 py-1.5">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={`Search ${label.toLowerCase()}…`}
                className="w-full rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs text-[#111827] placeholder:text-[#9CA3AF] focus:border-[#1B3A5C] focus:outline-none"
              />
            </div>
          )}

          <div className="max-h-72 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-center text-xs text-[#9CA3AF]">
                No matches
              </div>
            ) : (
              filtered.map((opt) => {
                const checked = selectedSet.has(opt.id)
                return (
                  <button
                    type="button"
                    key={opt.id}
                    onClick={() => toggle(opt.id)}
                    className="flex w-full items-start gap-2 px-3 py-1.5 text-left text-sm hover:bg-[#F9FAFB]"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      readOnly
                      className="mt-1 h-3.5 w-3.5 shrink-0 accent-[#1B3A5C]"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[#111827]">{opt.label}</span>
                      {opt.secondary && opt.secondary !== opt.label && (
                        <span className="block truncate text-[10px] text-[#6B7280]">
                          {opt.secondary}
                        </span>
                      )}
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}
