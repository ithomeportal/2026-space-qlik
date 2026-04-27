"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import {
  ArrowLeft,
  DollarSign,
  Loader2,
  Percent,
  Target,
  TrendingUp,
  Truck,
} from "lucide-react"
import {
  BudgetFilters,
  BudgetMonthPoint,
  useBudgetByCustomer,
  useBudgetByTeam,
  useBudgetFilters,
  useBudgetMonthly,
  useBudgetSummary,
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
const USD2 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
})
const COUNT = new Intl.NumberFormat("en-US")
const PCT1 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
})

const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))
const fmtUsd2 = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD2.format(Number(v))
const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT.format(Number(v))
const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT1.format(Number(v))}%`

type Metric = "revenue" | "loads" | "profit"

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`
}

function clampToYear(iso: string) {
  if (iso < YEAR_START) return YEAR_START
  if (iso > YEAR_END) return YEAR_END
  return iso
}

type Preset = "full" | "ytd" | "custom"

export default function BudgetFollowUp2026Page() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["budget-followup-2026"]]}>
      <BudgetFollowUp2026Content />
    </RoleGuard>
  )
}

function BudgetFollowUp2026Content() {
  const [preset, setPreset] = useState<Preset>("full")
  const [startDate, setStartDate] = useState<string>(YEAR_START)
  const [endDate, setEndDate] = useState<string>(YEAR_END)
  const [teams, setTeams] = useState<string[]>([])
  const [customer, setCustomer] = useState<string | undefined>(undefined)
  const [metric, setMetric] = useState<Metric>("revenue")
  const [sort, setSort] = useState("revenue_actual_desc")
  const [page, setPage] = useState(1)
  const limit = 100

  const appliedDates = useMemo(() => {
    if (preset === "full") return { startDate: YEAR_START, endDate: YEAR_END }
    if (preset === "ytd") return { startDate: YEAR_START, endDate: clampToYear(todayIso()) }
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

  const { data: teamRes } = useBudgetByTeam(filters)
  const teamRows = teamRes?.data ?? []

  const { data: custRes, isLoading: loadingCustomers } = useBudgetByCustomer(
    filters,
    sort,
    page,
    limit,
  )
  const customers = custRes?.data ?? []
  const customerTotal = custRes?.meta?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(customerTotal / limit))

  const toggleTeam = (t: string) => {
    setTeams((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
    setPage(1)
  }

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
          Window: {appliedDates.startDate} → {appliedDates.endDate}
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
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {[
                { k: "revenue" as const, label: "Revenue" },
                { k: "loads" as const, label: "Loads" },
                { k: "profit" as const, label: "Profit" },
              ].map((opt) => (
                <button
                  key={opt.k}
                  onClick={() => setMetric(opt.k)}
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
          </div>
          <MonthlyChart data={monthly} metric={metric} loading={loadingMonthly} />
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

        {/* Per-customer table */}
        <section>
          <div className="mb-2 flex items-end justify-between gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-[#6B7280]">
              By Customer ({fmtCount(customerTotal)})
            </h2>
            <select
              value={sort}
              onChange={(e) => {
                setSort(e.target.value)
                setPage(1)
              }}
              className="rounded-lg border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs"
            >
              <option value="revenue_actual_desc">Sort: Revenue Actual ↓</option>
              <option value="revenue_variance_desc">Sort: Revenue variance ↓</option>
              <option value="revenue_variance_asc">Sort: Revenue variance ↑</option>
              <option value="profit_actual_desc">Sort: Profit Actual ↓</option>
              <option value="profit_variance_desc">Sort: Profit variance ↓</option>
              <option value="loads_actual_desc">Sort: Loads Actual ↓</option>
              <option value="customer">Sort: Customer A–Z</option>
            </select>
          </div>

          <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-[#F9FAFB] text-xs uppercase tracking-wider text-[#6B7280]">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Customer</th>
                    <th className="px-3 py-2 text-right font-medium">Loads A / B</th>
                    <th className="px-3 py-2 text-right font-medium">Loads Var</th>
                    <th className="px-3 py-2 text-right font-medium">Revenue A</th>
                    <th className="px-3 py-2 text-right font-medium">Revenue B</th>
                    <th className="px-3 py-2 text-right font-medium">Revenue Var</th>
                    <th className="px-3 py-2 text-right font-medium">Profit A</th>
                    <th className="px-3 py-2 text-right font-medium">Profit Var</th>
                    <th className="px-3 py-2 text-right font-medium">Margin A / B</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F3F4F6]">
                  {loadingCustomers && customers.length === 0 && (
                    <tr>
                      <td colSpan={9} className="px-3 py-6 text-center">
                        <Loader2 className="mx-auto h-5 w-5 animate-spin text-[#6B7280]" />
                      </td>
                    </tr>
                  )}
                  {!loadingCustomers && customers.length === 0 && (
                    <tr>
                      <td
                        colSpan={9}
                        className="px-3 py-6 text-center text-xs text-[#9CA3AF]"
                      >
                        No customers match the current filters
                      </td>
                    </tr>
                  )}
                  {customers.map((c) => {
                    const loadsVar = Number(c.loads_variance)
                    const revVar = Number(c.revenue_variance)
                    const profVar = Number(c.profit_variance)
                    return (
                      <tr
                        key={c.customer_name}
                        className={`cursor-pointer ${
                          customer === c.customer_name ? "bg-[#EFF6FF]" : "hover:bg-[#F9FAFB]"
                        }`}
                        onClick={() =>
                          setCustomer(
                            customer === c.customer_name ? undefined : c.customer_name,
                          )
                        }
                      >
                        <td className="px-3 py-2 font-medium text-[#111827]">
                          {c.customer_name}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                          {fmtCount(c.loads_actual)} / {fmtCount(c.loads_budget)}
                        </td>
                        <td
                          className={`px-3 py-2 text-right tabular-nums font-medium ${
                            loadsVar >= 0 ? "text-[#059669]" : "text-[#DC2626]"
                          }`}
                        >
                          {loadsVar >= 0 ? "+" : ""}
                          {fmtCount(loadsVar)}
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
                        <td
                          className={`px-3 py-2 text-right tabular-nums font-semibold ${
                            profVar >= 0 ? "text-[#059669]" : "text-[#DC2626]"
                          }`}
                        >
                          {profVar >= 0 ? "+" : ""}
                          {fmtUsd(profVar)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-[#374151]">
                          {fmtPct(c.margin_actual_pct)} /{" "}
                          <span className="text-[#6B7280]">
                            {fmtPct(c.margin_budget_pct)}
                          </span>
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

function MonthlyChart({
  data,
  metric,
  loading,
}: {
  data: BudgetMonthPoint[]
  metric: Metric
  loading?: boolean
}) {
  const values = useMemo(() => {
    const actualKey = `${metric}_actual` as const
    const budgetKey = `${metric}_budget` as const
    return data.map((d) => ({
      month: d.month_date,
      actual: Number(d[actualKey] ?? 0),
      budget: Number(d[budgetKey] ?? 0),
    }))
  }, [data, metric])

  const max = useMemo(
    () => Math.max(1, ...values.flatMap((v) => [v.actual, v.budget])),
    [values],
  )

  const fmt = metric === "loads" ? fmtCount : fmtUsd
  const fmtLarge = (n: number) => {
    if (metric === "loads") return fmtCount(n)
    if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
    if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(0)}K`
    return fmtUsd2(n)
  }

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
        No monthly data in range
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-12 gap-2 px-1">
        {values.map((v) => {
          const actualH = (v.actual / max) * 160
          const budgetH = (v.budget / max) * 160
          const variance = v.actual - v.budget
          const varianceOk = variance >= 0
          return (
            <div
              key={v.month}
              className="flex flex-col items-center gap-1"
              title={`${new Date(`${v.month}T00:00:00Z`).toLocaleDateString("en-US", {
                month: "short",
                year: "numeric",
                timeZone: "UTC",
              })}\nActual: ${fmt(v.actual)}\nBudget: ${fmt(v.budget)}`}
            >
              <div className="flex h-40 items-end gap-1">
                <div
                  className="w-3 rounded-t bg-gradient-to-t from-[#1B3A5C] to-[#3B82F6]"
                  style={{ height: `${actualH}px` }}
                />
                <div
                  className="w-3 rounded-t bg-[#E5E7EB]"
                  style={{ height: `${budgetH}px` }}
                />
              </div>
              <div className="text-[10px] text-[#6B7280]">
                {new Date(`${v.month}T00:00:00Z`).toLocaleDateString("en-US", {
                  month: "short",
                  timeZone: "UTC",
                })}
              </div>
              <div
                className={`text-[10px] font-medium ${
                  varianceOk ? "text-[#059669]" : "text-[#DC2626]"
                }`}
              >
                {varianceOk ? "▲" : "▼"} {fmtLarge(Math.abs(variance))}
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
