"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import {
  ArrowLeft,
  Loader2,
  PiggyBank,
  TrendingDown,
  TrendingUp,
  Truck,
} from "lucide-react"
import {
  useSavingsByCustomer,
  useSavingsLanes,
  useSavingsMonths,
  useSavingsSummary,
} from "@/lib/api"

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

export default function ESavingsFromCarriersPage() {
  const [month, setMonth] = useState<string | undefined>(undefined)
  const [origin, setOrigin] = useState("")
  const [dest, setDest] = useState("")
  const [customerId, setCustomerId] = useState<string | undefined>(undefined)
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

  const { data: summaryRes, isLoading: loadingSummary } = useSavingsSummary(
    effectiveMonth,
    customerId,
  )
  const summary = summaryRes?.data
  const { data: byCustomerRes } = useSavingsByCustomer(effectiveMonth, 25)
  const customers = byCustomerRes?.data ?? []

  const lanesFilters = useMemo(
    () => ({ month: effectiveMonth, customerId, origin, dest, sort, page, limit }),
    [effectiveMonth, customerId, origin, dest, sort, page],
  )
  const { data: lanesRes, isLoading: loadingLanes } = useSavingsLanes(lanesFilters)
  const lanes = lanesRes?.data ?? []
  const totalLanes = lanesRes?.meta?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(totalLanes / limit))

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
          Base: {summary?.base_month ?? "—"}
          {" · "}
          Month: {fmtMonth(effectiveMonth)}
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-6 px-6 py-6">
        {/* Month selector */}
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

          {customerId && (
            <button
              onClick={() => setCustomerId(undefined)}
              className="rounded-full border border-[#E5E7EB] bg-white px-3 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
            >
              Clear customer filter
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
          />
        </section>

        {/* Secondary KPIs */}
        <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <MiniKpi label="High-Vol Lanes (≥8)" value={fmtCount(summary?.high_vol_lanes)} />
          <MiniKpi label="HV + Savings" value={fmtCount(summary?.high_vol_savings_lanes)} />
          <MiniKpi label="Low-Vol Lanes (1–7)" value={fmtCount(summary?.low_vol_lanes)} />
          <MiniKpi label="LV + Savings" value={fmtCount(summary?.low_vol_savings_lanes)} />
        </section>

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
                  {customers.map((c) => (
                    <tr
                      key={c.customer_id}
                      onClick={() => {
                        setCustomerId(c.customer_id)
                        setPage(1)
                      }}
                      className={`cursor-pointer transition-colors ${
                        customerId === c.customer_id
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
                  ))}
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
                <input
                  value={origin}
                  onChange={(e) => {
                    setOrigin(e.target.value)
                    setPage(1)
                  }}
                  placeholder="Origin contains…"
                  className="w-40 rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-xs focus:border-[#1B3A5C] focus:outline-none"
                />
                <input
                  value={dest}
                  onChange={(e) => {
                    setDest(e.target.value)
                    setPage(1)
                  }}
                  placeholder="Destination contains…"
                  className="w-40 rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-xs focus:border-[#1B3A5C] focus:outline-none"
                />
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
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F3F4F6]">
                    {loadingLanes && lanes.length === 0 && (
                      <tr>
                        <td colSpan={8} className="px-3 py-6 text-center">
                          <Loader2 className="mx-auto h-5 w-5 animate-spin text-[#6B7280]" />
                        </td>
                      </tr>
                    )}
                    {!loadingLanes && lanes.length === 0 && (
                      <tr>
                        <td
                          colSpan={8}
                          className="px-3 py-6 text-center text-xs text-[#9CA3AF]"
                        >
                          No lanes match the current filters
                        </td>
                      </tr>
                    )}
                    {lanes.map((lane) => (
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
                          {fmtCurrency(lane.base_lane)}
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
                      </tr>
                    ))}
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
}

function KpiCard({ label, value, icon, tone, loading }: KpiCardProps) {
  const toneClasses = {
    neutral: "bg-gradient-to-br from-[#1B3A5C] to-[#2563EB]",
    positive: "bg-gradient-to-br from-[#065F46] to-[#10B981]",
    negative: "bg-gradient-to-br from-[#991B1B] to-[#EF4444]",
  }[tone]

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
    </div>
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
