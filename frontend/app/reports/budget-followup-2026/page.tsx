"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import {
  ArrowLeft,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  DollarSign,
  Loader2,
  Percent,
  Target,
  TrendingUp,
  Truck,
} from "lucide-react"
import {
  BudgetCustomerDetailRow,
  BudgetCustomerRow,
  BudgetFilters,
  BudgetMetricCell,
  BudgetMonthPoint,
  BudgetTop5Row,
  BudgetWeekPoint,
  useBudgetByCustomer,
  useBudgetByCustomerDetail,
  useBudgetByTeam,
  useBudgetFilters,
  useBudgetMonthly,
  useBudgetSummary,
  useBudgetTop5,
  useBudgetWeekly,
} from "@/lib/api"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"

const YEAR_START = "2026-01-01"
const YEAR_END = "2026-12-31"

const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const COUNT = new Intl.NumberFormat("en-US")
const COUNT0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 })
const PCT1 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
})

const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))
const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT.format(Number(v))
const fmtInt = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : COUNT0.format(Math.round(Number(v)))
const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT1.format(Number(v))}%`

// Compact $ formatter for chart bar labels.
const fmtUsdCompact = (n: number) => {
  const sign = n < 0 ? "-" : ""
  const abs = Math.abs(n)
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(0)}K`
  return `${sign}$${abs.toFixed(0)}`
}

type Metric = "revenue" | "loads" | "profit"
type Preset = "full" | "ytd" | "mtd" | "custom"
type CustomerTab = "overview" | "revenue" | "profit" | "loads"
type SortDir = "asc" | "desc"

type OverviewSortKey =
  | "customer_name"
  | "loads_actual"
  | "loads_budget"
  | "loads_variance"
  | "revenue_actual"
  | "revenue_budget"
  | "revenue_variance"
  | "profit_actual"
  | "profit_budget"
  | "profit_variance"
  | "margin_actual_pct"
  | "margin_budget_pct"

const OVERVIEW_SORT_PARAM: Record<OverviewSortKey, { desc: string; asc: string }> = {
  customer_name:      { desc: "customer", asc: "customer" },
  loads_actual:       { desc: "loads_actual_desc", asc: "loads_actual_desc" },
  loads_budget:       { desc: "loads_actual_desc", asc: "loads_actual_desc" },
  loads_variance:     { desc: "revenue_variance_desc", asc: "revenue_variance_asc" },
  revenue_actual:     { desc: "revenue_actual_desc", asc: "revenue_actual_desc" },
  revenue_budget:     { desc: "revenue_actual_desc", asc: "revenue_actual_desc" },
  revenue_variance:   { desc: "revenue_variance_desc", asc: "revenue_variance_asc" },
  profit_actual:      { desc: "profit_actual_desc", asc: "profit_actual_desc" },
  profit_budget:      { desc: "profit_actual_desc", asc: "profit_actual_desc" },
  profit_variance:    { desc: "profit_variance_desc", asc: "profit_variance_desc" },
  margin_actual_pct:  { desc: "revenue_actual_desc", asc: "revenue_actual_desc" },
  margin_budget_pct:  { desc: "revenue_actual_desc", asc: "revenue_actual_desc" },
}

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`
}

function yesterdayIso() {
  const d = new Date()
  d.setDate(d.getDate() - 1)
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

export default function BudgetFollowUp2026Page() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["budget-followup-2026"]]}>
      <BudgetFollowUp2026Content />
    </RoleGuard>
  )
}

function BudgetFollowUp2026Content() {
  // Default range — month-to-yesterday (per Bruno's PDF feedback, 2026-04-28).
  const [preset, setPreset] = useState<Preset>("full")
  const [startDate, setStartDate] = useState<string>(YEAR_START)
  const [endDate, setEndDate] = useState<string>(YEAR_END)
  const [teams, setTeams] = useState<string[]>([])
  const [customer, setCustomer] = useState<string | undefined>(undefined)
  const [metric, setMetric] = useState<Metric>("revenue")
  const [weeklyMetric, setWeeklyMetric] = useState<Metric>("revenue")
  const [sort, setSort] = useState("revenue_actual_desc")
  const [overviewSort, setOverviewSort] = useState<{ key: OverviewSortKey; dir: SortDir }>({
    key: "revenue_actual",
    dir: "desc",
  })
  const [page, setPage] = useState(1)
  const [tab, setTab] = useState<CustomerTab>("overview")
  const limit = 100

  const appliedDates = useMemo(() => {
    if (preset === "full") return { startDate: YEAR_START, endDate: YEAR_END }
    if (preset === "ytd")
      return { startDate: YEAR_START, endDate: clampToYear(yesterdayIso()) }
    if (preset === "mtd")
      return { startDate: clampToYear(monthStartIso()), endDate: clampToYear(todayIso()) }
    return { startDate: clampToYear(startDate), endDate: clampToYear(endDate) }
  }, [preset, startDate, endDate])

  const filters: BudgetFilters = useMemo(
    () => ({ ...appliedDates, teams, customer }),
    [appliedDates, teams, customer],
  )

  const { data: filterOptionsRes, isLoading: loadingFilters } = useBudgetFilters()
  const filterOptions = filterOptionsRes?.data

  const { data: summaryRes, isLoading: loadingSummary } = useBudgetSummary(filters)
  const s = summaryRes?.data

  const { data: monthlyRes, isLoading: loadingMonthly } = useBudgetMonthly(filters)
  const monthly = monthlyRes?.data ?? []

  const { data: weeklyRes, isLoading: loadingWeekly } = useBudgetWeekly(filters)
  const weekly = weeklyRes?.data ?? []

  const { data: top5Res } = useBudgetTop5(filters)
  const top5 = top5Res?.data

  const { data: teamRes } = useBudgetByTeam(filters)
  const teamRows = teamRes?.data ?? []

  const { data: custRes, isLoading: loadingCustomers } = useBudgetByCustomer(
    filters,
    sort,
    page,
    limit,
  )
  const customers = useMemo(() => custRes?.data ?? [], [custRes])
  const customerTotal = custRes?.meta?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(customerTotal / limit))

  const { data: detailRes, isLoading: loadingDetail } = useBudgetByCustomerDetail(filters)
  const detailRows = detailRes?.data ?? []

  // Apply overview-tab click-to-sort over the page rows. Backend returns rows
  // already sorted by the dropdown sort key; client-side reorder is just a UI
  // affordance over the current page (so paging still works).
  const overviewSorted = useMemo(() => {
    const rows = [...customers]
    const { key, dir } = overviewSort
    const factor = dir === "asc" ? 1 : -1
    rows.sort((a, b) => {
      if (key === "customer_name") {
        return a.customer_name.localeCompare(b.customer_name) * factor
      }
      const av = Number((a as unknown as Record<string, unknown>)[key] ?? 0)
      const bv = Number((b as unknown as Record<string, unknown>)[key] ?? 0)
      return (av - bv) * factor
    })
    return rows
  }, [customers, overviewSort])

  const toggleTeam = (t: string) => {
    setTeams((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
    setPage(1)
  }

  const onOverviewHeaderClick = (key: OverviewSortKey) => {
    setOverviewSort((prev) => {
      const dir: SortDir = prev.key === key && prev.dir === "desc" ? "asc" : "desc"
      // Mirror to the backend sort param so paging stays consistent.
      const backendSort = OVERVIEW_SORT_PARAM[key][dir]
      setSort(backendSort)
      setPage(1)
      return { key, dir }
    })
  }

  const rangeLabel =
    preset === "mtd"
      ? "MTD"
      : preset === "ytd"
      ? "YTD"
      : preset === "full"
      ? "Full 2026"
      : "Custom"

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
          <Target className="h-4 w-4 text-[#2563EB]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">
            2026 Official Budget Follow Up
          </h1>
          <span className="rounded-full bg-[#F3F4F6] px-2 py-0.5 text-xs text-[#6B7280]">
            Operations
          </span>
        </div>
        <div className="ml-auto text-xs text-[#6B7280]">
          {rangeLabel}: {appliedDates.startDate} → {appliedDates.endDate}
          {" · "}
          Teams: {teams.length ? teams.join(", ") : "all"}
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-6 px-6 py-6">
        {/* Filters row */}
        <section className="flex flex-wrap items-center gap-4 rounded-lg border border-[#E5E7EB] bg-white px-4 py-3 shadow-sm">
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Range
            </label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {[
                { k: "full" as const, label: "Full 2026" },
                { k: "ytd" as const, label: "YTD" },
                { k: "mtd" as const, label: "MTD" },
                { k: "custom" as const, label: "Custom" },
              ].map((opt) => (
                <button
                  key={opt.k}
                  onClick={() => {
                    setPreset(opt.k)
                    setPage(1)
                  }}
                  className={`px-3 py-1.5 ${
                    preset === opt.k
                      ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                      : "text-[#6B7280] hover:text-[#111827]"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {preset === "custom" && (
              <div className="flex items-center gap-1 text-xs">
                <input
                  type="date"
                  min={YEAR_START}
                  max={YEAR_END}
                  value={startDate}
                  onChange={(e) => {
                    setStartDate(e.target.value)
                    setPage(1)
                  }}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
                <span className="text-[#6B7280]">→</span>
                <input
                  type="date"
                  min={YEAR_START}
                  max={YEAR_END}
                  value={endDate}
                  onChange={(e) => {
                    setEndDate(e.target.value)
                    setPage(1)
                  }}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Teams
            </label>
            {loadingFilters ? (
              <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />
            ) : (
              <div className="flex flex-wrap gap-1">
                {(filterOptions?.teams ?? []).map((t) => (
                  <button
                    key={t}
                    onClick={() => toggleTeam(t)}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      teams.includes(t)
                        ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                        : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                    }`}
                  >
                    {t}
                  </button>
                ))}
                {teams.length > 0 && (
                  <button
                    onClick={() => {
                      setTeams([])
                      setPage(1)
                    }}
                    className="rounded-full border border-[#E5E7EB] bg-white px-3 py-1 text-xs text-[#6B7280] hover:bg-[#F3F4F6]"
                  >
                    Clear
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Customer
            </label>
            <select
              value={customer ?? ""}
              onChange={(e) => {
                setCustomer(e.target.value || undefined)
                setPage(1)
              }}
              className="max-w-[260px] rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            >
              <option value="">All customers</option>
              {(filterOptions?.customers ?? []).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
        </section>

        {/* Primary KPIs */}
        <section className="grid grid-cols-1 gap-4 md:grid-cols-4">
          <BudgetKpi
            label="Loads"
            icon={<Truck className="h-5 w-5" />}
            actual={fmtCount(s?.loads_actual)}
            budget={fmtCount(s?.loads_budget)}
            variance={s?.loads_variance}
            variancePretty={fmtCount(s?.loads_variance)}
            achievement={s?.loads_achievement_pct}
            loading={loadingSummary}
            tone="neutral"
          />
          <BudgetKpi
            label="Revenue"
            icon={<DollarSign className="h-5 w-5" />}
            actual={fmtUsd(s?.revenue_actual)}
            budget={fmtUsd(s?.revenue_budget)}
            variance={s?.revenue_variance}
            variancePretty={fmtUsd(s?.revenue_variance)}
            achievement={s?.revenue_achievement_pct}
            loading={loadingSummary}
            tone="positive"
          />
          <BudgetKpi
            label="Profit"
            icon={<TrendingUp className="h-5 w-5" />}
            actual={fmtUsd(s?.profit_actual)}
            budget={fmtUsd(s?.profit_budget)}
            variance={s?.profit_variance}
            variancePretty={fmtUsd(s?.profit_variance)}
            achievement={s?.profit_achievement_pct}
            loading={loadingSummary}
            tone={s && s.profit_variance >= 0 ? "positive" : "negative"}
          />
          <BudgetKpi
            label="Margin %"
            icon={<Percent className="h-5 w-5" />}
            actual={fmtPct(s?.margin_actual_pct)}
            budget={fmtPct(s?.margin_budget_pct)}
            variance={s?.margin_variance_pct}
            variancePretty={
              s?.margin_variance_pct !== undefined
                ? `${s.margin_variance_pct >= 0 ? "+" : ""}${PCT1.format(s.margin_variance_pct)} pp`
                : "—"
            }
            achievement={
              s && s.margin_budget_pct !== 0
                ? (s.margin_actual_pct / s.margin_budget_pct) * 100
                : undefined
            }
            loading={loadingSummary}
            tone={s && s.margin_variance_pct >= 0 ? "positive" : "negative"}
          />
        </section>

        {/* Secondary KPIs */}
        <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <MiniKpi label="Days Elapsed" value={fmtCount(s?.days_elapsed)} hint={`of ${fmtCount(s?.total_days)}`} />
          <MiniKpi label="Days Remaining" value={fmtCount(s?.days_remaining)} />
          <MiniKpi
            label="Active Customers"
            value={fmtCount(s?.active_customers)}
            hint={`of ${fmtCount(s?.total_customers)}`}
          />
          <MiniKpi label="Active Days" value={fmtCount(s?.active_days)} />
        </section>

        {/* Monthly chart */}
        <section className="rounded-lg border border-[#E5E7EB] bg-white p-4 shadow-sm">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-[#6B7280]">
              Monthly — Actual vs Budget
            </h2>
            <MetricToggle metric={metric} onChange={setMetric} />
          </div>
          <PeriodChart
            kind="month"
            data={monthly}
            metric={metric}
            loading={loadingMonthly}
          />
        </section>

        {/* Weekly chart (last 12 ISO weeks, current excluded) */}
        <section className="rounded-lg border border-[#E5E7EB] bg-white p-4 shadow-sm">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-[#6B7280]">
              Last 12 Weeks — Actual vs Budget
            </h2>
            <MetricToggle metric={weeklyMetric} onChange={setWeeklyMetric} />
          </div>
          <PeriodChart
            kind="week"
            data={weekly}
            metric={weeklyMetric}
            loading={loadingWeekly}
          />
        </section>

        {/* Per-team cards */}
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-[#6B7280]">
            By Team
          </h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {teamRows.length === 0 && (
              <div className="col-span-full rounded-lg border border-dashed border-[#E5E7EB] bg-white p-4 text-center text-xs text-[#9CA3AF]">
                No team rollup data
              </div>
            )}
            {teamRows.map((t) => {
              const revVar = Number(t.revenue_actual) - Number(t.revenue_budget)
              return (
                <div
                  key={t.team_id}
                  className="rounded-lg border border-[#E5E7EB] bg-white p-3 shadow-sm"
                >
                  <div className="text-xs font-semibold text-[#1B3A5C]">{t.team_id}</div>
                  <div className="mt-2 space-y-1 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="text-[#6B7280]">Loads</span>
                      <span className="tabular-nums text-[#111827]">
                        {fmtCount(t.loads_actual)} / {fmtCount(t.loads_budget)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-[#6B7280]">Revenue</span>
                      <span className="tabular-nums text-[#111827]">
                        {fmtUsd(t.revenue_actual)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-[#6B7280]">Profit</span>
                      <span className="tabular-nums text-[#111827]">
                        {fmtUsd(t.profit_actual)}
                      </span>
                    </div>
                    <div
                      className={`flex items-center justify-between font-medium ${
                        revVar >= 0 ? "text-[#059669]" : "text-[#DC2626]"
                      }`}
                    >
                      <span>Rev variance</span>
                      <span className="tabular-nums">
                        {revVar >= 0 ? "+" : ""}
                        {fmtUsd(revVar)}
                      </span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        {/* 5 Top-N tables — Bruno's 2026-04-28 feedback */}
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-[#6B7280]">
            Leaderboards
          </h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
            <Top5Card title="Top Volume" rows={top5?.top_volume ?? []} field="loads_var" tone="positive" valueFmt={fmtInt} />
            <Top5Card title="Worst Volume" rows={top5?.worst_volume ?? []} field="loads_var" tone="negative" valueFmt={fmtInt} />
            <Top5Card title="Top Profit" rows={top5?.top_profit ?? []} field="profit_var" tone="positive" valueFmt={fmtUsd} />
            <Top5Card title="Worst Profit" rows={top5?.worst_profit ?? []} field="profit_var" tone="negative" valueFmt={fmtUsd} />
            <Top5Card title="Non-Budget Active Account" rows={top5?.non_budget ?? []} field="profit_actual" tone="neutral" valueFmt={fmtUsd} />
          </div>
        </section>

        {/* By Customer with tabs */}
        <section>
          <div className="mb-2 flex flex-wrap items-end justify-between gap-3">
            <div className="flex items-end gap-3">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-[#6B7280]">
                By Customer ({fmtCount(customerTotal)})
              </h2>
              <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
                {[
                  { k: "overview" as const, label: "Overview" },
                  { k: "revenue" as const, label: "Revenue" },
                  { k: "profit" as const, label: "Profit" },
                  { k: "loads" as const, label: "Loads" },
                ].map((t) => (
                  <button
                    key={t.k}
                    onClick={() => setTab(t.k)}
                    className={`px-3 py-1.5 ${
                      tab === t.k
                        ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                        : "text-[#6B7280] hover:text-[#111827]"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {tab === "overview" && (
            <OverviewTable
              rows={overviewSorted}
              loading={loadingCustomers}
              sortKey={overviewSort.key}
              sortDir={overviewSort.dir}
              onHeaderClick={onOverviewHeaderClick}
              activeCustomer={customer}
              onRowClick={(name) =>
                setCustomer(customer === name ? undefined : name)
              }
              page={page}
              pageCount={pageCount}
              onPagePrev={() => setPage((p) => Math.max(1, p - 1))}
              onPageNext={() => setPage((p) => Math.min(pageCount, p + 1))}
            />
          )}

          {tab !== "overview" && (
            <DetailTable
              rows={detailRows}
              metricKey={tab}
              loading={loadingDetail}
              activeCustomer={customer}
              onRowClick={(name) =>
                setCustomer(customer === name ? undefined : name)
              }
              isCurrency={tab !== "loads"}
            />
          )}
        </section>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

function MetricToggle({
  metric,
  onChange,
}: {
  metric: Metric
  onChange: (m: Metric) => void
}) {
  return (
    <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
      {[
        { k: "revenue" as const, label: "Revenue" },
        { k: "loads" as const, label: "Loads" },
        { k: "profit" as const, label: "Profit" },
      ].map((opt) => (
        <button
          key={opt.k}
          onClick={() => onChange(opt.k)}
          className={`px-3 py-1.5 ${
            metric === opt.k
              ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
              : "text-[#6B7280] hover:text-[#111827]"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

interface BudgetKpiProps {
  label: string
  icon: React.ReactNode
  actual: string
  budget: string
  variance: number | null | undefined
  variancePretty: string
  achievement: number | null | undefined
  loading?: boolean
  tone: "neutral" | "positive" | "negative"
}

function BudgetKpi({
  label,
  icon,
  actual,
  budget,
  variance,
  variancePretty,
  achievement,
  loading,
  tone,
}: BudgetKpiProps) {
  const toneClasses = {
    neutral: "bg-gradient-to-br from-[#1B3A5C] to-[#2563EB]",
    positive: "bg-gradient-to-br from-[#065F46] to-[#10B981]",
    negative: "bg-gradient-to-br from-[#991B1B] to-[#EF4444]",
  }[tone]
  const vcolor =
    variance === null || variance === undefined
      ? "text-[#6B7280]"
      : variance >= 0
      ? "text-[#059669]"
      : "text-[#DC2626]"
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
          actual
        )}
      </div>
      <div className="mt-1 text-xs text-[#6B7280]">
        Budget <span className="tabular-nums text-[#374151]">{budget}</span>
      </div>
      <div className={`mt-2 flex items-center gap-2 text-xs font-medium ${vcolor}`}>
        <span>
          {variance !== null && variance !== undefined && variance >= 0 ? "+" : ""}
          {variancePretty}
        </span>
        {achievement !== null && achievement !== undefined && (
          <span className="rounded-full bg-[#F3F4F6] px-2 py-0.5 text-[10px] uppercase tracking-wider text-[#6B7280]">
            {PCT1.format(achievement)}% of budget
          </span>
        )}
      </div>
    </div>
  )
}

function MiniKpi({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-[#111827]">{value}</div>
      {hint && <div className="text-[10px] text-[#9CA3AF]">{hint}</div>}
    </div>
  )
}

interface PeriodPoint {
  loads_actual: number
  loads_budget: number
  revenue_actual: number
  revenue_budget: number
  profit_actual: number
  profit_budget: number
}

function PeriodChart({
  kind,
  data,
  metric,
  loading,
}: {
  kind: "month" | "week"
  data: BudgetMonthPoint[] | BudgetWeekPoint[]
  metric: Metric
  loading?: boolean
}) {
  const values = useMemo(() => {
    const actualKey = `${metric}_actual` as const
    const budgetKey = `${metric}_budget` as const
    return (data as Array<PeriodPoint & { month_date?: string; week_start?: string }>).map(
      (d) => ({
        label: kind === "month" ? d.month_date! : d.week_start!,
        actual: Number(d[actualKey] ?? 0),
        budget: Number(d[budgetKey] ?? 0),
      }),
    )
  }, [data, metric, kind])

  const max = useMemo(
    () => Math.max(1, ...values.flatMap((v) => [v.actual, v.budget])),
    [values],
  )

  const fmt = metric === "loads" ? fmtCount : fmtUsd

  if (loading && values.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#9CA3AF]" />
      </div>
    )
  }
  if (values.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-xs text-[#9CA3AF]">
        No data in range
      </div>
    )
  }

  const colCount = values.length
  const gridStyle = { gridTemplateColumns: `repeat(${colCount}, minmax(0, 1fr))` }

  return (
    <div className="space-y-2">
      <div className="grid gap-2 px-1" style={gridStyle}>
        {values.map((v) => {
          const actualH = (v.actual / max) * 160
          const budgetH = (v.budget / max) * 160
          const variance = v.actual - v.budget
          const varianceOk = variance >= 0
          const dt = new Date(`${v.label}T00:00:00Z`)
          const labelText =
            kind === "month"
              ? dt.toLocaleDateString("en-US", { month: "short", timeZone: "UTC" })
              : dt.toLocaleDateString("en-US", {
                  month: "numeric",
                  day: "numeric",
                  timeZone: "UTC",
                })
          return (
            <div
              key={v.label}
              className="flex flex-col items-center gap-1"
              title={`${
                kind === "month"
                  ? dt.toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" })
                  : `Week of ${dt.toLocaleDateString("en-US", { timeZone: "UTC" })}`
              }\nActual: ${fmt(v.actual)}\nBudget: ${fmt(v.budget)}`}
            >
              <div className="relative flex h-44 items-end gap-1">
                <div
                  className="w-3 rounded-t bg-gradient-to-t from-[#1B3A5C] to-[#3B82F6]"
                  style={{ height: `${actualH}px` }}
                />
                <div
                  className="w-3 rounded-t bg-[#E5E7EB]"
                  style={{ height: `${budgetH}px` }}
                />
              </div>
              {/* Always-on actual amount label, even when bar is short */}
              <div className="text-[10px] font-semibold tabular-nums text-[#1B3A5C]">
                {metric === "loads" ? fmtInt(v.actual) : fmtUsdCompact(v.actual)}
              </div>
              <div className="text-[10px] text-[#6B7280]">{labelText}</div>
              <div
                className={`text-[10px] font-medium ${
                  varianceOk ? "text-[#059669]" : "text-[#DC2626]"
                }`}
              >
                {varianceOk ? "▲" : "▼"}{" "}
                {metric === "loads"
                  ? fmtInt(Math.abs(variance))
                  : fmtUsdCompact(Math.abs(variance))}
              </div>
            </div>
          )
        })}
      </div>
      <div className="flex items-center justify-center gap-4 text-xs text-[#6B7280]">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 rounded bg-gradient-to-r from-[#1B3A5C] to-[#3B82F6]" />
          Actual
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 rounded bg-[#E5E7EB]" />
          Budget
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Top-5 leaderboard card
// ---------------------------------------------------------------------------

function Top5Card({
  title,
  rows,
  field,
  tone,
  valueFmt,
}: {
  title: string
  rows: BudgetTop5Row[]
  field: "loads_var" | "profit_var" | "profit_actual"
  tone: "positive" | "negative" | "neutral"
  valueFmt: (v: number | null | undefined) => string
}) {
  const toneClass =
    tone === "positive"
      ? "text-[#059669]"
      : tone === "negative"
      ? "text-[#DC2626]"
      : "text-[#1B3A5C]"

  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
        {title}
      </div>
      {rows.length === 0 ? (
        <div className="py-2 text-center text-[10px] text-[#9CA3AF]">No customers</div>
      ) : (
        <ul className="space-y-1">
          {rows.map((r) => {
            const value = Number(r[field] ?? 0)
            return (
              <li
                key={r.customer_name}
                className="flex items-center justify-between gap-2 text-[11px]"
              >
                <span className="truncate text-[#374151]" title={r.customer_name}>
                  {r.customer_name}
                </span>
                <span className={`shrink-0 tabular-nums font-semibold ${toneClass}`}>
                  {value > 0 ? "+" : ""}
                  {valueFmt(value)}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Overview table — Bruno's column splits + click-to-sort
// ---------------------------------------------------------------------------

function HeaderCell({
  label,
  align = "right",
  sortKey,
  activeKey,
  activeDir,
  onClick,
}: {
  label: string
  align?: "left" | "right"
  sortKey: OverviewSortKey
  activeKey: OverviewSortKey
  activeDir: SortDir
  onClick: (k: OverviewSortKey) => void
}) {
  const active = activeKey === sortKey
  const Icon = !active ? ArrowUpDown : activeDir === "desc" ? ArrowDown : ArrowUp
  return (
    <th
      onClick={() => onClick(sortKey)}
      className={`cursor-pointer select-none px-3 py-2 ${
        align === "left" ? "text-left" : "text-right"
      } font-medium hover:text-[#111827]`}
    >
      <span className={`inline-flex items-center gap-1 ${active ? "text-[#1B3A5C]" : ""}`}>
        {label}
        <Icon className="h-3 w-3 opacity-60" />
      </span>
    </th>
  )
}

function OverviewTable({
  rows,
  loading,
  sortKey,
  sortDir,
  onHeaderClick,
  activeCustomer,
  onRowClick,
  page,
  pageCount,
  onPagePrev,
  onPageNext,
}: {
  rows: BudgetCustomerRow[]
  loading: boolean
  sortKey: OverviewSortKey
  sortDir: SortDir
  onHeaderClick: (k: OverviewSortKey) => void
  activeCustomer?: string
  onRowClick: (customer_name: string) => void
  page: number
  pageCount: number
  onPagePrev: () => void
  onPageNext: () => void
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-[#F9FAFB] text-xs uppercase tracking-wider text-[#6B7280]">
            <tr>
              <HeaderCell label="Customer" align="left" sortKey="customer_name" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
              <HeaderCell label="Loads A" sortKey="loads_actual" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
              <HeaderCell label="Loads B" sortKey="loads_budget" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
              <HeaderCell label="Loads Var" sortKey="loads_variance" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
              <HeaderCell label="Revenue A" sortKey="revenue_actual" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
              <HeaderCell label="Revenue B" sortKey="revenue_budget" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
              <HeaderCell label="Revenue Var" sortKey="revenue_variance" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
              <HeaderCell label="Profit A" sortKey="profit_actual" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
              <HeaderCell label="Profit B" sortKey="profit_budget" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
              <HeaderCell label="Profit Var" sortKey="profit_variance" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
              <HeaderCell label="Margin A" sortKey="margin_actual_pct" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
              <HeaderCell label="Margin B" sortKey="margin_budget_pct" activeKey={sortKey} activeDir={sortDir} onClick={onHeaderClick} />
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {loading && rows.length === 0 && (
              <tr>
                <td colSpan={12} className="px-3 py-6 text-center">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin text-[#6B7280]" />
                </td>
              </tr>
            )}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={12} className="px-3 py-6 text-center text-xs text-[#9CA3AF]">
                  No customers match the current filters
                </td>
              </tr>
            )}
            {rows.map((c) => {
              const loadsVar = Number(c.loads_variance)
              const revVar = Number(c.revenue_variance)
              const profVar = Number(c.profit_variance)
              return (
                <tr
                  key={c.customer_name}
                  className={`cursor-pointer ${
                    activeCustomer === c.customer_name
                      ? "bg-[#EFF6FF]"
                      : "hover:bg-[#F9FAFB]"
                  }`}
                  onClick={() => onRowClick(c.customer_name)}
                >
                  <td className="px-3 py-2 font-medium text-[#111827]">{c.customer_name}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                    {fmtInt(c.loads_actual)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#6B7280]">
                    {fmtInt(c.loads_budget)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums font-medium ${
                      loadsVar >= 0 ? "text-[#059669]" : "text-[#DC2626]"
                    }`}
                  >
                    {loadsVar >= 0 ? "+" : ""}
                    {fmtInt(loadsVar)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                    {fmtUsd(c.revenue_actual)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#6B7280]">
                    {fmtUsd(c.revenue_budget)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums font-semibold ${
                      revVar >= 0 ? "text-[#059669]" : "text-[#DC2626]"
                    }`}
                  >
                    {revVar >= 0 ? "+" : ""}
                    {fmtUsd(revVar)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                    {fmtUsd(c.profit_actual)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#6B7280]">
                    {fmtUsd(c.profit_budget)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums font-semibold ${
                      profVar >= 0 ? "text-[#059669]" : "text-[#DC2626]"
                    }`}
                  >
                    {profVar >= 0 ? "+" : ""}
                    {fmtUsd(profVar)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                    {fmtPct(c.margin_actual_pct)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#6B7280]">
                    {fmtPct(c.margin_budget_pct)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2 text-xs text-[#6B7280]">
        <div>
          Page {page} of {pageCount}
        </div>
        <div className="flex gap-1">
          <button
            disabled={page <= 1}
            onClick={onPagePrev}
            className="rounded-md border border-[#E5E7EB] bg-white px-3 py-1 disabled:opacity-40 hover:bg-[#F3F4F6]"
          >
            Prev
          </button>
          <button
            disabled={page >= pageCount}
            onClick={onPageNext}
            className="rounded-md border border-[#E5E7EB] bg-white px-3 py-1 disabled:opacity-40 hover:bg-[#F3F4F6]"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Detail tabs (Revenue / Profit / Loads)
// ---------------------------------------------------------------------------

type DetailSortKey =
  | "customer_name"
  | "actual"
  | "budget"
  | "var"
  | "avg_last_month"
  | "avg_week"
  | "avg_day"
  | "projected"

function DetailTable({
  rows,
  metricKey,
  loading,
  activeCustomer,
  onRowClick,
  isCurrency,
}: {
  rows: BudgetCustomerDetailRow[]
  metricKey: "revenue" | "profit" | "loads"
  loading: boolean
  activeCustomer?: string
  onRowClick: (customer_name: string) => void
  isCurrency: boolean
}) {
  const [sortKey, setSortKey] = useState<DetailSortKey>("actual")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const onHeaderClick = (k: DetailSortKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"))
    } else {
      setSortKey(k)
      setSortDir("desc")
    }
  }

  const sorted = useMemo(() => {
    const factor = sortDir === "asc" ? 1 : -1
    const sliced = [...rows]
    sliced.sort((a, b) => {
      if (sortKey === "customer_name") {
        return a.customer_name.localeCompare(b.customer_name) * factor
      }
      const av = Number(a[metricKey][sortKey as keyof BudgetMetricCell] ?? 0)
      const bv = Number(b[metricKey][sortKey as keyof BudgetMetricCell] ?? 0)
      return (av - bv) * factor
    })
    return sliced
  }, [rows, metricKey, sortKey, sortDir])

  const fmtVal = (v: number | null | undefined) =>
    isCurrency ? fmtUsd(v) : fmtInt(v)

  const Header = ({
    label,
    k,
    align = "right",
  }: {
    label: string
    k: DetailSortKey
    align?: "left" | "right"
  }) => {
    const active = sortKey === k
    const Icon = !active ? ArrowUpDown : sortDir === "desc" ? ArrowDown : ArrowUp
    return (
      <th
        onClick={() => onHeaderClick(k)}
        className={`cursor-pointer select-none px-3 py-2 ${
          align === "left" ? "text-left" : "text-right"
        } font-medium hover:text-[#111827]`}
      >
        <span className={`inline-flex items-center gap-1 ${active ? "text-[#1B3A5C]" : ""}`}>
          {label}
          <Icon className="h-3 w-3 opacity-60" />
        </span>
      </th>
    )
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-[#F9FAFB] text-xs uppercase tracking-wider text-[#6B7280]">
            <tr>
              <Header label="Customer" k="customer_name" align="left" />
              <Header label="Actual" k="actual" />
              <Header label="Budget" k="budget" />
              <Header label="Var" k="var" />
              <Header label="AVG × Last Month" k="avg_last_month" />
              <Header label="AVG × Week" k="avg_week" />
              <Header label="AVG × Day" k="avg_day" />
              <Header label="Projected" k="projected" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {loading && sorted.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin text-[#6B7280]" />
                </td>
              </tr>
            )}
            {!loading && sorted.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-xs text-[#9CA3AF]">
                  No customers match the current filters
                </td>
              </tr>
            )}
            {sorted.map((r) => {
              const cell = r[metricKey]
              const v = Number(cell.var)
              return (
                <tr
                  key={r.customer_name}
                  className={`cursor-pointer ${
                    activeCustomer === r.customer_name
                      ? "bg-[#EFF6FF]"
                      : "hover:bg-[#F9FAFB]"
                  }`}
                  onClick={() => onRowClick(r.customer_name)}
                >
                  <td className="px-3 py-2 font-medium text-[#111827]">{r.customer_name}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                    {fmtVal(cell.actual)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#6B7280]">
                    {fmtVal(cell.budget)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums font-semibold ${
                      v >= 0 ? "text-[#059669]" : "text-[#DC2626]"
                    }`}
                  >
                    {v >= 0 ? "+" : ""}
                    {fmtVal(v)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                    {fmtVal(cell.avg_last_month)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                    {fmtVal(cell.avg_week)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                    {fmtVal(cell.avg_day)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums font-semibold text-[#1B3A5C]">
                    {fmtVal(cell.projected)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
