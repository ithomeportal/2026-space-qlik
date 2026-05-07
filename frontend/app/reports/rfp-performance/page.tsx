"use client"

import { Suspense, useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, FileText, Loader2, X } from "lucide-react"
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  EMPTY_FILTERS,
  useRfpConvertioRatio,
  useRfpDetails,
  useRfpFilterOptions,
  useRfpPotentialByMonth,
  useRfpSummary,
  useRfpSummaryByCustomer,
  useRfpSummaryByCustomerDetail,
  useRfpSummaryByTab,
  useRfpTrend12m,
  type RfpDetailSort,
  type RfpFilters,
  type RfpStatusBlock,
  type RfpWonBlock,
} from "@/lib/rfp-performance-api"
import { ReportGuard } from "@/components/ReportGuard"
import { ErrorBanner } from "./ErrorBanner"
import {
  daysBetween,
  daysToEndClass,
  fmtCount,
  fmtDate,
  fmtMoney,
  fmtMonth,
  fmtPct,
  statusPillClass,
} from "./format"

// ---------------------------------------------------------------------------
// Page wrapper
// ---------------------------------------------------------------------------

export default function RfpPerformancePage() {
  return (
    <ReportGuard reportKey="rfp-performance">
      <Suspense
        fallback={
          <div className="flex min-h-[60vh] items-center justify-center text-xs text-[#6B7280]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Loading…
          </div>
        }
      >
        <Content />
      </Suspense>
    </ReportGuard>
  )
}

// ---------------------------------------------------------------------------
// Default = YTD (computed in browser TZ; server also pins to YTD if unset).
// ---------------------------------------------------------------------------

function ytdRange(): { from: string; to: string } {
  const now = new Date()
  const y = now.getFullYear()
  const from = `${y}-01-01`
  const m = String(now.getMonth() + 1).padStart(2, "0")
  const d = String(now.getDate()).padStart(2, "0")
  return { from, to: `${y}-${m}-${d}` }
}

// ---------------------------------------------------------------------------
// Main content
// ---------------------------------------------------------------------------

function Content() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  const ytd = useMemo(() => ytdRange(), [])

  const filters: RfpFilters = useMemo(
    () => ({
      ...EMPTY_FILTERS,
      dateFrom: searchParams.get("date_from") || ytd.from,
      dateTo: searchParams.get("date_to") || ytd.to,
      divisions: parseList(searchParams.get("division")),
      departments: parseList(searchParams.get("department")),
      businessTypes: parseList(searchParams.get("business_type")),
      customers: parseList(searchParams.get("customer")),
      types: parseList(searchParams.get("type_quotation")),
      statuses: parseList(searchParams.get("status")),
    }),
    [searchParams, ytd.from, ytd.to],
  )

  const summaryTab = (searchParams.get("sum_tab") as "operations" | "sales" | "division") || "operations"
  const customerTab = (searchParams.get("cust_tab") as "summary" | "detail") || "summary"
  const detailSort = (searchParams.get("det_sort") as RfpDetailSort) || "submitted_desc"
  const detailPage = Math.max(1, Number(searchParams.get("det_page")) || 1)

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

  const setFilter = (key: keyof RfpFilters, values: string[]) => {
    const param = {
      divisions: "division",
      departments: "department",
      businessTypes: "business_type",
      customers: "customer",
      types: "type_quotation",
      statuses: "status",
    }[key as Exclude<keyof RfpFilters, "dateFrom" | "dateTo">]
    if (!param) return
    updateUrl({ [param]: values.length ? values.join(",") : null })
  }

  const setDate = (from: string | null, to: string | null) => {
    updateUrl({
      date_from: from === ytd.from ? null : from,
      date_to: to === ytd.to ? null : to,
    })
  }

  const optionsRes = useRfpFilterOptions()
  const opts = optionsRes.data?.data
  const summaryQ = useRfpSummary(filters)
  const convertioQ = useRfpConvertioRatio(filters)
  const trendQ = useRfpTrend12m(filters)
  const monthQ = useRfpPotentialByMonth(filters)
  const tabQ = useRfpSummaryByTab(filters, summaryTab)
  const custQ = useRfpSummaryByCustomer(filters)
  const custDetailQ = useRfpSummaryByCustomerDetail(filters)
  const detailsQ = useRfpDetails(filters, detailPage, detailSort)

  const summary = summaryQ.data?.data
  const asOf = opts?.as_of

  const anyFilter =
    filters.divisions.length +
      filters.departments.length +
      filters.businessTypes.length +
      filters.customers.length +
      filters.types.length +
      filters.statuses.length >
    0

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
          <FileText className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">
            Performance for RFPs
          </h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-[10px] text-[#1E40AF]">
            rfp tracker
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          {asOf && <span>Loaded: {fmtDate(asOf.slice(0, 10))}</span>}
          {(optionsRes.isFetching || summaryQ.isFetching) && (
            <Loader2 className="h-3 w-3 animate-spin text-[#6B7280]" />
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto grid w-full max-w-[1920px] grid-cols-2 gap-3 px-6 py-3 md:grid-cols-4 lg:grid-cols-7">
          <DateRange
            from={filters.dateFrom}
            to={filters.dateTo}
            ytdFrom={ytd.from}
            ytdTo={ytd.to}
            onChange={setDate}
          />
          <FilterPill
            label="Division"
            options={opts?.divisions ?? []}
            selected={filters.divisions}
            onChange={(v) => setFilter("divisions", v)}
          />
          <FilterPill
            label="Department"
            options={opts?.departments ?? []}
            selected={filters.departments}
            onChange={(v) => setFilter("departments", v)}
          />
          <FilterPill
            label="Bussiness Type"
            options={opts?.business_types ?? []}
            selected={filters.businessTypes}
            onChange={(v) => setFilter("businessTypes", v)}
          />
          <FilterPill
            label="Customer"
            options={opts?.customers ?? []}
            selected={filters.customers}
            onChange={(v) => setFilter("customers", v)}
            searchable
          />
          <FilterPill
            label="Type"
            options={opts?.types ?? []}
            selected={filters.types}
            onChange={(v) => setFilter("types", v)}
          />
          <FilterPill
            label="Status"
            options={opts?.statuses ?? []}
            selected={filters.statuses}
            onChange={(v) => setFilter("statuses", v)}
            searchable
          />
        </div>
        {anyFilter && (
          <div className="border-t border-[#F3F4F6] bg-[#F9FAFB] px-6 py-1.5 text-[11px] text-[#6B7280]">
            <button
              onClick={() => {
                setFilter("divisions", [])
                setFilter("departments", [])
                setFilter("businessTypes", [])
                setFilter("customers", [])
                setFilter("types", [])
                setFilter("statuses", [])
              }}
              className="font-semibold text-[#1B3A5C] hover:underline"
            >
              Clear all filters
            </button>
          </div>
        )}
      </div>

      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-4 px-6 py-4">
        <ErrorBanner
          errors={[
            optionsRes.error,
            summaryQ.error,
            convertioQ.error,
            trendQ.error,
            monthQ.error,
            tabQ.error,
            custQ.error,
            custDetailQ.error,
            detailsQ.error,
          ]}
        />

        {/* Grand total */}
        <PotentialRevenueBanner value={summary?.grand_total_pot_rev} loading={summaryQ.isLoading} />

        {/* Status blocks */}
        <StatusBlock
          title="Open"
          subtitle="All statuses other than Won and Lost."
          tone={openTone}
          block={summary?.open}
          loading={summaryQ.isLoading}
        />
        <StatusBlock
          title="Closed"
          subtitle="Won + Lost."
          tone={closedTone}
          block={summary?.closed}
          loading={summaryQ.isLoading}
        />
        <StatusBlock
          title="Lost"
          subtitle="status = 'Lost'."
          tone={lostTone}
          block={summary?.lost}
          loading={summaryQ.isLoading}
        />
        <WonBlock
          block={summary?.won}
          grand={summary?.grand_total_pot_rev}
          loading={summaryQ.isLoading}
        />

        {/* Convertio Ratio table + 12-mo combos */}
        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ConvertioRatioTable
            data={convertioQ.data?.data}
            loading={convertioQ.isLoading}
          />
          <div className="grid grid-cols-1 gap-4">
            <TrendComboPanel
              title="Volume Awarded / Convertio Ratio"
              subtitle="Bars: Volume Won (rfp_volume) · Line: Volume Won / Total Loads · last 12 months · ignores Date filter"
              data={trendQ.data?.data?.rows ?? []}
              valueKey="volume_won"
              ratioKey="volume_conv_ratio"
              valueLabel="Volume Won"
              ratioLabel="Conv Ratio"
              loading={trendQ.isLoading}
              fmt="int"
            />
            <TrendComboPanel
              title="Revenue Awarded / Convertio Ratio"
              subtitle="Bars: Revenue Won (rfp_revenue) · Line: Revenue Won / Potential Revenue · last 12 months · ignores Date filter"
              data={trendQ.data?.data?.rows ?? []}
              valueKey="revenue_won"
              ratioKey="revenue_conv_ratio"
              valueLabel="Revenue Won"
              ratioLabel="Conv Ratio"
              loading={trendQ.isLoading}
              fmt="money"
            />
          </div>
        </section>

        {/* RFP Summary tabbed */}
        <Panel title="RFP Summary">
          <div className="-mt-2 mb-2 flex gap-1 border-b border-[#E5E7EB]">
            {(["operations", "sales", "division"] as const).map((k) => (
              <button
                key={k}
                onClick={() =>
                  updateUrl({ sum_tab: k === "operations" ? null : k })
                }
                className={`-mb-px border-b-2 px-3 py-1.5 text-xs font-medium ${
                  summaryTab === k
                    ? "border-[#1B3A5C] text-[#1B3A5C]"
                    : "border-transparent text-[#6B7280] hover:text-[#111827]"
                }`}
              >
                by {k.charAt(0).toUpperCase() + k.slice(1)}
              </button>
            ))}
          </div>
          <SummaryByTabTable
            rows={tabQ.data?.data?.rows ?? []}
            totals={tabQ.data?.data?.totals}
            loading={tabQ.isLoading}
          />
        </Panel>

        {/* Potential Revenue Per Month (full history, ignore date filter) */}
        <Panel
          title="Potential Revenue Per Month"
          subtitle="Full history · ignores Date filter"
        >
          <PotentialPerMonthTable
            rows={monthQ.data?.data?.rows ?? []}
            loading={monthQ.isLoading}
          />
        </Panel>

        {/* Customer summary tabbed */}
        <Panel>
          <div className="-mt-2 mb-2 flex gap-1 border-b border-[#E5E7EB]">
            <button
              onClick={() => updateUrl({ cust_tab: null })}
              className={`-mb-px border-b-2 px-3 py-1.5 text-xs font-medium ${
                customerTab === "summary"
                  ? "border-[#1B3A5C] text-[#1B3A5C]"
                  : "border-transparent text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              RFP Summary by Customer
            </button>
            <button
              onClick={() => updateUrl({ cust_tab: "detail" })}
              className={`-mb-px border-b-2 px-3 py-1.5 text-xs font-medium ${
                customerTab === "detail"
                  ? "border-[#1B3A5C] text-[#1B3A5C]"
                  : "border-transparent text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              RFP Summary with Convertio Ratio
            </button>
          </div>
          {customerTab === "summary" ? (
            <CustomerSummaryTable
              rows={custQ.data?.data?.rows ?? []}
              loading={custQ.isLoading}
              onPickCustomer={(c) => setFilter("customers", [c])}
            />
          ) : (
            <CustomerDetailTable
              rows={custDetailQ.data?.data?.rows ?? []}
              loading={custDetailQ.isLoading}
            />
          )}
        </Panel>

        {/* RFP Details */}
        <Panel title="RFP Details">
          <DetailsTable
            rows={detailsQ.data?.data?.rows ?? []}
            total={detailsQ.data?.meta?.total ?? 0}
            page={detailPage}
            sort={detailSort}
            loading={detailsQ.isLoading}
            setPage={(p) => updateUrl({ det_page: p === 1 ? null : String(p) })}
            setSort={(s) =>
              updateUrl({
                det_sort: s === "submitted_desc" ? null : s,
                det_page: null,
              })
            }
          />
        </Panel>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Status block tones (PDF: blue/purple/red/green frames)
// ---------------------------------------------------------------------------

interface Tone {
  border: string
  ring: string
  headline: string
  card: string
  text: string
}

const openTone: Tone = {
  border: "border-[#93C5FD]",
  ring: "border-[#3B82F6]",
  headline: "text-[#1E40AF]",
  card: "border-[#3B82F6]",
  text: "text-[#1E40AF]",
}
const closedTone: Tone = {
  border: "border-[#C4B5FD]",
  ring: "border-[#7C3AED]",
  headline: "text-[#5B21B6]",
  card: "border-[#7C3AED]",
  text: "text-[#5B21B6]",
}
const lostTone: Tone = {
  border: "border-[#FCA5A5]",
  ring: "border-[#DC2626]",
  headline: "text-[#991B1B]",
  card: "border-[#DC2626]",
  text: "text-[#991B1B]",
}
const wonTone: Tone = {
  border: "border-[#86EFAC]",
  ring: "border-[#16A34A]",
  headline: "text-[#166534]",
  card: "border-[#16A34A]",
  text: "text-[#166534]",
}

// ---------------------------------------------------------------------------
// Banner — grand-total Potential Revenue
// ---------------------------------------------------------------------------

function PotentialRevenueBanner({
  value,
  loading,
}: {
  value: number | undefined
  loading: boolean
}) {
  return (
    <section className="rounded-xl border-2 border-[#93C5FD] bg-white px-6 py-4">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        Potential Revenue
      </div>
      <div className="mt-1 text-3xl font-semibold tabular-nums text-[#1B3A5C]">
        {loading ? <Loader2 className="inline h-6 w-6 animate-spin" /> : fmtMoney(value)}
      </div>
      <div className="mt-0.5 text-[10px] text-[#9CA3AF]">
        Sum(potential_revenue) · respects all filter pills
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Status block — 9 KPI cards
// ---------------------------------------------------------------------------

function StatusBlock({
  title,
  subtitle,
  tone,
  block,
  loading,
}: {
  title: string
  subtitle: string
  tone: Tone
  block: RfpStatusBlock | undefined
  loading: boolean
}) {
  return (
    <section className={`rounded-xl border-2 ${tone.border} bg-white p-3`}>
      <div className="mb-2 px-1">
        <div className={`text-xs font-semibold ${tone.headline}`}>{title}</div>
        <div className="text-[10px] text-[#6B7280]">{subtitle}</div>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-9">
        <KpiCard label="RFPs" value={fmtCount(block?.rfps)} tone={tone} loading={loading} />
        <KpiCard label="Offer Lanes" value={fmtCount(block?.offer_lanes)} tone={tone} loading={loading} />
        <KpiCard label="Lane Quoted" value={fmtCount(block?.lane_quoted)} tone={tone} loading={loading} />
        <KpiCard label="Lane Participation %" value={fmtPct(block?.lane_participation_pct)} tone={tone} loading={loading} />
        <KpiCard label="Total Offer Load Count" value={fmtCount(block?.total_offer_loads)} tone={tone} loading={loading} />
        <KpiCard label="Load Count Quoted" value={fmtCount(block?.load_count_quoted)} tone={tone} loading={loading} />
        <KpiCard label="Volume Participation %" value={fmtPct(block?.volume_participation_pct)} tone={tone} loading={loading} />
        <KpiCard label="Potential Revenue" value={fmtMoney(block?.potential_revenue, { compact: true })} tone={tone} loading={loading} />
        <KpiCard label="% Potential Rev" value={fmtPct(block?.pct_potential_rev)} tone={tone} loading={loading} />
      </div>
    </section>
  )
}

function WonBlock({
  block,
  grand: _grand,
  loading,
}: {
  block: RfpWonBlock | undefined
  grand: number | undefined
  loading: boolean
}) {
  void _grand
  return (
    <section className={`rounded-xl border-2 ${wonTone.border} bg-white p-3`}>
      <div className="mb-2 px-1">
        <div className={`text-xs font-semibold ${wonTone.headline}`}>Won</div>
        <div className="text-[10px] text-[#6B7280]">status = &apos;Won&apos;.</div>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-9">
        <KpiCard label="RFPs" value={fmtCount(block?.rfps)} tone={wonTone} loading={loading} />
        <KpiCard label="Offer Lanes" value={fmtCount(block?.offer_lanes)} tone={wonTone} loading={loading} />
        <KpiCard label="Lane Quoted" value={fmtCount(block?.lane_quoted)} tone={wonTone} loading={loading} />
        <KpiCard label="Lane Participation %" value={fmtPct(block?.lane_participation_pct)} tone={wonTone} loading={loading} />
        <KpiCard label="Total Offer Load Count" value={fmtCount(block?.total_offer_loads)} tone={wonTone} loading={loading} />
        <KpiCard label="Load Count Quoted" value={fmtCount(block?.load_count_quoted)} tone={wonTone} loading={loading} />
        <KpiCard label="Volume Participation %" value={fmtPct(block?.volume_participation_pct)} tone={wonTone} loading={loading} />
        <KpiCard label="Potential Revenue" value={fmtMoney(block?.potential_revenue, { compact: true })} tone={wonTone} loading={loading} />
        <KpiCard label="% Potential Rev" value={fmtPct(block?.pct_potential_rev)} tone={wonTone} loading={loading} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-6">
        <KpiCard label="Lane Awarded" value={fmtCount(block?.lane_awarded)} tone={wonTone} loading={loading} />
        <KpiCard label="Lane Awarded Ratio %" value={fmtPct(block?.lane_awarded_ratio_pct)} tone={wonTone} loading={loading} />
        <KpiCard label="Load Awarded" value={fmtCount(block?.load_awarded)} tone={wonTone} loading={loading} />
        <KpiCard label="Load Awarded Ratio %" value={fmtPct(block?.load_awarded_ratio_pct)} tone={wonTone} loading={loading} />
        <KpiCard label="Awarded Revenue" value={fmtMoney(block?.awarded_revenue, { compact: true })} tone={wonTone} loading={loading} />
        <KpiCard label="Awarded Convertio Ratio" value={fmtPct(block?.awarded_convertio_ratio)} tone={wonTone} loading={loading} />
      </div>
    </section>
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
  tone: Tone
  loading: boolean
}) {
  return (
    <div className={`flex flex-col rounded-lg border ${tone.card} bg-white px-3 py-2`}>
      <div className="text-[9px] font-medium uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className={`mt-1 text-base font-semibold tabular-nums ${tone.text}`}>
        {loading ? "…" : value}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Convertio Ratio table — 0.5%→5% sensitivity
// ---------------------------------------------------------------------------

function ConvertioRatioTable({
  data,
  loading,
}: {
  data:
    | {
        pot_rev_closed: number
        revenue_awarded: number
        rows: Array<{
          ratio: number
          revenue_awarded_at_ratio: number
          actual_vs_conv_ratio: number
          pot_rev_gp_15: number
        }>
      }
    | undefined
  loading: boolean
}) {
  return (
    <Panel
      title="Convertio Ratio by Status Won and Lost"
      subtitle={
        data
          ? `Potential Revenue Closed: ${fmtMoney(data.pot_rev_closed)} || Revenue Awarded: ${fmtMoney(data.revenue_awarded)}`
          : ""
      }
    >
      <TableShell loading={loading} empty={!loading && (!data || data.rows.length === 0)} cols={4}>
        <thead className="bg-[#ECFDF5] text-left text-[10px] uppercase tracking-wider text-[#065F46]">
          <tr>
            <th className="px-3 py-2 font-semibold">Convertio Ratio</th>
            <th className="px-3 py-2 text-right font-semibold">Revenue Awarded</th>
            <th className="px-3 py-2 text-right font-semibold">Actual vs Conv. Ratio%</th>
            <th className="px-3 py-2 text-right font-semibold">Pot Rev GP 15%</th>
          </tr>
        </thead>
        <tbody>
          {data?.rows.map((r) => {
            const positive = r.actual_vs_conv_ratio > 0
            const negative = r.actual_vs_conv_ratio < 0
            return (
              <tr key={r.ratio} className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]">
                <td className="px-3 py-1.5 font-medium tabular-nums text-[#111827]">
                  {(r.ratio * 100).toFixed(2)}%
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums text-[#374151]">
                  {fmtMoney(r.revenue_awarded_at_ratio)}
                </td>
                <td
                  className={`px-3 py-1.5 text-right tabular-nums font-semibold ${
                    positive
                      ? "bg-[#DCFCE7] text-[#166534]"
                      : negative
                        ? "bg-[#FEE2E2] text-[#991B1B]"
                        : "text-[#374151]"
                  }`}
                >
                  {fmtMoney(r.actual_vs_conv_ratio)}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums text-[#374151]">
                  {fmtMoney(r.pot_rev_gp_15)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </TableShell>
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Trend combo chart
// ---------------------------------------------------------------------------

interface TrendRow {
  ym: string
  volume_won: number
  volume_conv_ratio: number | null
  revenue_won: number
  revenue_conv_ratio: number | null
}

function TrendComboPanel({
  title,
  subtitle,
  data,
  valueKey,
  ratioKey,
  valueLabel,
  ratioLabel,
  loading,
  fmt,
}: {
  title: string
  subtitle: string
  data: TrendRow[]
  valueKey: "volume_won" | "revenue_won"
  ratioKey: "volume_conv_ratio" | "revenue_conv_ratio"
  valueLabel: string
  ratioLabel: string
  loading: boolean
  fmt: "int" | "money"
}) {
  const chart = useMemo(
    () =>
      data.map((r) => ({
        label: fmtMonth(r.ym),
        value: r[valueKey],
        ratio:
          r[ratioKey] === null || r[ratioKey] === undefined
            ? 0
            : Number((r[ratioKey] as number * 100).toFixed(2)),
      })),
    [data, valueKey, ratioKey],
  )

  return (
    <Panel title={title} subtitle={subtitle}>
      {loading ? (
        <div className="flex h-[260px] items-center justify-center text-[11px] text-[#6B7280]">
          <Loader2 className="mr-1 h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : chart.length === 0 ? (
        <div className="flex h-[260px] items-center justify-center text-[11px] text-[#6B7280]">
          No data in the last 12 months.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={chart}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} />
            <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fontSize: 10 }}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              formatter={(v, name) => {
                if (name === ratioLabel) return `${Number(v).toFixed(2)}%`
                return fmt === "money" ? fmtMoney(Number(v)) : fmtCount(Number(v))
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar
              yAxisId="left"
              dataKey="value"
              fill="#1B3A5C"
              name={valueLabel}
              barSize={20}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="ratio"
              stroke="#7C2D12"
              name={ratioLabel}
              dot={{ r: 2 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

function SummaryByTabTable({
  rows,
  totals,
  loading,
}: {
  rows: Array<{ division: string; potential_revenue: number; potential_wo: number; awarded: number; conv: number | null }>
  totals: { potential_revenue: number; potential_wo: number; awarded: number; conv: number | null } | undefined
  loading: boolean
}) {
  return (
    <TableShell loading={loading} empty={!loading && rows.length === 0} cols={5}>
      <thead className="bg-[#F9FAFB] text-left text-[10px] uppercase tracking-wider text-[#6B7280]">
        <tr>
          <th className="px-3 py-2 font-semibold">Division</th>
          <th className="px-3 py-2 text-right font-semibold">$ Potential Revenue</th>
          <th className="px-3 py-2 text-right font-semibold">Potential W/O</th>
          <th className="px-3 py-2 text-right font-semibold">Awarded</th>
          <th className="px-3 py-2 text-right font-semibold">Conv</th>
        </tr>
      </thead>
      <tbody>
        {totals && (
          <tr className="border-b border-[#E5E7EB] bg-[#F3F4F6] font-semibold">
            <td className="px-3 py-2">Totals</td>
            <td className="px-3 py-2 text-right tabular-nums">{fmtMoney(totals.potential_revenue)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{fmtMoney(totals.potential_wo)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{fmtMoney(totals.awarded)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{fmtPct(totals.conv)}</td>
          </tr>
        )}
        {rows.map((r) => (
          <tr key={r.division} className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]">
            <td className="px-3 py-1.5 font-medium text-[#111827]">{r.division}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.potential_revenue)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.potential_wo)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.awarded)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtPct(r.conv)}</td>
          </tr>
        ))}
      </tbody>
    </TableShell>
  )
}

function PotentialPerMonthTable({
  rows,
  loading,
}: {
  rows: Array<{ ym: string; potential_closed: number; revenue_awarded: number }>
  loading: boolean
}) {
  const totalPot = rows.reduce((a, b) => a + b.potential_closed, 0)
  const totalAw = rows.reduce((a, b) => a + b.revenue_awarded, 0)
  return (
    <TableShell loading={loading} empty={!loading && rows.length === 0} cols={3}>
      <thead className="bg-[#FCE7F3] text-left text-[10px] uppercase tracking-wider text-[#9D174D]">
        <tr>
          <th className="px-3 py-2 font-semibold">Date</th>
          <th className="px-3 py-2 text-right font-semibold">Potential Closed</th>
          <th className="px-3 py-2 text-right font-semibold">Revenue Awarded</th>
        </tr>
      </thead>
      <tbody>
        <tr className="border-b border-[#E5E7EB] bg-[#F3F4F6] font-semibold">
          <td className="px-3 py-2">Totals</td>
          <td className="px-3 py-2 text-right tabular-nums">{fmtMoney(totalPot)}</td>
          <td className="px-3 py-2 text-right tabular-nums">{fmtMoney(totalAw)}</td>
        </tr>
        {rows.map((r) => (
          <tr key={r.ym} className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]">
            <td className="px-3 py-1.5 text-[#111827]">{fmtMonth(r.ym)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.potential_closed)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.revenue_awarded)}</td>
          </tr>
        ))}
      </tbody>
    </TableShell>
  )
}

function CustomerSummaryTable({
  rows,
  loading,
  onPickCustomer,
}: {
  rows: Array<{
    customer: string
    bids: number
    total_lanes: number
    lanes_quoted: number
    lanes_ratio_pct: number | null
    total_volume: number
    volume_quoted: number
    volume_ratio_pct: number | null
    potential_revenue: number
    awarded_revenue: number
    awarded_conv_ratio_pct: number | null
  }>
  loading: boolean
  onPickCustomer: (c: string) => void
}) {
  const tot = useMemo(() => {
    return rows.reduce(
      (a, r) => ({
        bids: a.bids + r.bids,
        total_lanes: a.total_lanes + r.total_lanes,
        lanes_quoted: a.lanes_quoted + r.lanes_quoted,
        total_volume: a.total_volume + r.total_volume,
        volume_quoted: a.volume_quoted + r.volume_quoted,
        potential_revenue: a.potential_revenue + r.potential_revenue,
        awarded_revenue: a.awarded_revenue + r.awarded_revenue,
      }),
      { bids: 0, total_lanes: 0, lanes_quoted: 0, total_volume: 0, volume_quoted: 0, potential_revenue: 0, awarded_revenue: 0 },
    )
  }, [rows])

  return (
    <TableShell loading={loading} empty={!loading && rows.length === 0} cols={11}>
      <thead className="bg-[#ECFDF5] text-left text-[10px] uppercase tracking-wider text-[#065F46]">
        <tr>
          <th className="px-3 py-2 font-semibold">Customer</th>
          <th className="px-3 py-2 text-right font-semibold"># Bids</th>
          <th className="px-3 py-2 text-right font-semibold">Total Lanes</th>
          <th className="px-3 py-2 text-right font-semibold">Lanes Quoted</th>
          <th className="px-3 py-2 text-right font-semibold">Lanes Ratio %</th>
          <th className="px-3 py-2 text-right font-semibold">Total Volume</th>
          <th className="px-3 py-2 text-right font-semibold">Volume Quoted</th>
          <th className="px-3 py-2 text-right font-semibold">Volume Ratio %</th>
          <th className="px-3 py-2 text-right font-semibold">$ Potencial Revenue</th>
          <th className="px-3 py-2 text-right font-semibold">Awarded Revenue</th>
          <th className="px-3 py-2 text-right font-semibold">Awarded Conv Ratio %</th>
        </tr>
      </thead>
      <tbody>
        <tr className="border-b border-[#E5E7EB] bg-[#F3F4F6] font-semibold">
          <td className="px-3 py-2">Totals</td>
          <td className="px-3 py-2 text-right tabular-nums">{fmtCount(tot.bids)}</td>
          <td className="px-3 py-2 text-right tabular-nums">{fmtCount(tot.total_lanes)}</td>
          <td className="px-3 py-2 text-right tabular-nums">{fmtCount(tot.lanes_quoted)}</td>
          <td className="px-3 py-2 text-right tabular-nums">
            {fmtPct(tot.total_lanes ? tot.lanes_quoted / tot.total_lanes : null)}
          </td>
          <td className="px-3 py-2 text-right tabular-nums">{fmtCount(tot.total_volume)}</td>
          <td className="px-3 py-2 text-right tabular-nums">{fmtCount(tot.volume_quoted)}</td>
          <td className="px-3 py-2 text-right tabular-nums">
            {fmtPct(tot.total_volume ? tot.volume_quoted / tot.total_volume : null)}
          </td>
          <td className="px-3 py-2 text-right tabular-nums">{fmtMoney(tot.potential_revenue)}</td>
          <td className="px-3 py-2 text-right tabular-nums">{fmtMoney(tot.awarded_revenue)}</td>
          <td className="px-3 py-2 text-right tabular-nums">
            {fmtPct(tot.potential_revenue ? tot.awarded_revenue / tot.potential_revenue : null)}
          </td>
        </tr>
        {rows.map((r, i) => (
          <tr key={`${r.customer}-${i}`} className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]">
            <td className="max-w-[14rem] truncate px-3 py-1.5 font-medium" title={r.customer}>
              <button
                onClick={() => onPickCustomer(r.customer)}
                className="text-left text-[#1B3A5C] hover:underline"
              >
                {r.customer}
              </button>
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.bids)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.total_lanes)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.lanes_quoted)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtPct(r.lanes_ratio_pct)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.total_volume)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.volume_quoted)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtPct(r.volume_ratio_pct)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.potential_revenue)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.awarded_revenue)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtPct(r.awarded_conv_ratio_pct)}</td>
          </tr>
        ))}
      </tbody>
    </TableShell>
  )
}

function CustomerDetailTable({
  rows,
  loading,
}: {
  rows: Array<{
    customer: string
    ym: string | null
    type_quotation: string
    total_lanes: number
    lanes_quoted: number
    lane_part_pct: number | null
    lanes_awarded: number
    lanes_conv_rat_pct: number | null
    total_volume: number
    volume_quoted: number
    volume_part_pct: number | null
    loads_awarded: number
    loads_conv_rat_pct: number | null
    potential_revenue: number
    rev_awarded: number
    rev_conv_ratio_pct: number | null
  }>
  loading: boolean
}) {
  return (
    <TableShell loading={loading} empty={!loading && rows.length === 0} cols={16}>
      <thead className="bg-[#FEE2E2] text-left text-[10px] uppercase tracking-wider text-[#991B1B]">
        <tr>
          <th className="px-3 py-2 font-semibold">Customer</th>
          <th className="px-3 py-2 font-semibold">Date</th>
          <th className="px-3 py-2 font-semibold">Type</th>
          <th className="px-3 py-2 text-right font-semibold">Total Lanes</th>
          <th className="px-3 py-2 text-right font-semibold">Lanes Quoted</th>
          <th className="px-3 py-2 text-right font-semibold">Lane Part %</th>
          <th className="px-3 py-2 text-right font-semibold">Lanes Awarded</th>
          <th className="px-3 py-2 text-right font-semibold">Lanes Conv Rat %</th>
          <th className="px-3 py-2 text-right font-semibold">Total Volume</th>
          <th className="px-3 py-2 text-right font-semibold">Volume Quoted</th>
          <th className="px-3 py-2 text-right font-semibold">Volume Part %</th>
          <th className="px-3 py-2 text-right font-semibold">Loads Awarded</th>
          <th className="px-3 py-2 text-right font-semibold">Loads Conv Rat %</th>
          <th className="px-3 py-2 text-right font-semibold">$ Pot Rev</th>
          <th className="px-3 py-2 text-right font-semibold">$ Rev Awarded</th>
          <th className="px-3 py-2 text-right font-semibold">Rev Conv Ratio %</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.customer}-${r.ym ?? ""}-${r.type_quotation}-${i}`} className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]">
            <td className="max-w-[12rem] truncate px-3 py-1.5 font-medium text-[#111827]" title={r.customer}>{r.customer}</td>
            <td className="px-3 py-1.5 text-[#374151]">{fmtMonth(r.ym)}</td>
            <td className="px-3 py-1.5 text-[#374151]">{r.type_quotation}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.total_lanes)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.lanes_quoted)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtPct(r.lane_part_pct)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.lanes_awarded)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtPct(r.lanes_conv_rat_pct)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.total_volume)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.volume_quoted)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtPct(r.volume_part_pct)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.loads_awarded)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtPct(r.loads_conv_rat_pct)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.potential_revenue)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.rev_awarded)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{fmtPct(r.rev_conv_ratio_pct)}</td>
          </tr>
        ))}
      </tbody>
    </TableShell>
  )
}

function DetailsTable({
  rows,
  total,
  page,
  sort,
  loading,
  setPage,
  setSort,
}: {
  rows: Array<{
    rfp_id: number | null
    month: string
    year: number | null
    customer: string
    division: string
    type_quotation: string
    total_lanes: number
    lanes_quoted: number
    lane_participation_pct: number | null
    lanes_awarded: number
    total_volume: number
    volume_quoted: number
    volume_participation_pct: number | null
    loads_awarded: number
    potential_revenue: number
    revenue_awarded: number
    status: string
    sales_executive: string
    submitted_date: string | null
    end_date: string | null
  }>
  total: number
  page: number
  sort: RfpDetailSort
  loading: boolean
  setPage: (p: number) => void
  setSort: (s: RfpDetailSort) => void
}) {
  const pageSize = 100
  const lastPage = Math.max(1, Math.ceil(total / pageSize))

  return (
    <>
      <TableShell loading={loading} empty={!loading && rows.length === 0} cols={20}>
        <thead className="bg-[#EDE9FE] text-left text-[10px] uppercase tracking-wider text-[#5B21B6]">
          <tr>
            <SortableTh label="RFP ID" k="rfp_desc" altK="rfp_asc" sort={sort} setSort={setSort} />
            <th className="px-3 py-2 font-semibold">Month</th>
            <th className="px-3 py-2 font-semibold">Year</th>
            <th className="px-3 py-2 font-semibold">Customer</th>
            <th className="px-3 py-2 font-semibold">Division</th>
            <th className="px-3 py-2 font-semibold">Type</th>
            <th className="px-3 py-2 text-right font-semibold">Total Lanes</th>
            <th className="px-3 py-2 text-right font-semibold">Lanes Quoted</th>
            <th className="px-3 py-2 text-right font-semibold">Lane Part %</th>
            <th className="px-3 py-2 text-right font-semibold">Lanes Awarded</th>
            <th className="px-3 py-2 text-right font-semibold">Total Volume</th>
            <th className="px-3 py-2 text-right font-semibold">Volume Quoted</th>
            <th className="px-3 py-2 text-right font-semibold">Volume Part %</th>
            <th className="px-3 py-2 text-right font-semibold">Loads Awarded</th>
            <SortableTh label="Potencial Revenue" k="potential_desc" altK="potential_asc" sort={sort} setSort={setSort} numeric />
            <SortableTh label="Revenue Awarded" k="awarded_desc" altK="awarded_asc" sort={sort} setSort={setSort} numeric />
            <th className="px-3 py-2 font-semibold">RFP Status</th>
            <th className="px-3 py-2 font-semibold">Sales Executive</th>
            <SortableTh label="Submitted" k="submitted_desc" altK="submitted_asc" sort={sort} setSort={setSort} />
            <th className="px-3 py-2 font-semibold">End Date</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const days = daysBetween(r.end_date)
            return (
              <tr key={`${r.rfp_id}-${i}`} className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]">
                <td className="px-3 py-1.5 tabular-nums text-[#6B7280]">{r.rfp_id ?? "—"}</td>
                <td className="px-3 py-1.5 text-[#374151]">{r.month}</td>
                <td className="px-3 py-1.5 tabular-nums text-[#374151]">{r.year ?? "—"}</td>
                <td className="max-w-[12rem] truncate px-3 py-1.5 font-medium text-[#111827]" title={r.customer}>
                  {r.customer || "—"}
                </td>
                <td className="px-3 py-1.5 text-[#374151]">{r.division}</td>
                <td className="px-3 py-1.5 text-[#374151]">{r.type_quotation || "—"}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.total_lanes)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.lanes_quoted)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtPct(r.lane_participation_pct)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.lanes_awarded)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.total_volume)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.volume_quoted)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtPct(r.volume_participation_pct)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.loads_awarded)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.potential_revenue)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.revenue_awarded)}</td>
                <td className="px-3 py-1.5">
                  <span
                    className={`inline-block rounded-md px-2 py-0.5 text-[10px] font-semibold ${statusPillClass(r.status)}`}
                  >
                    {r.status || "—"}
                  </span>
                </td>
                <td className="max-w-[10rem] truncate px-3 py-1.5 text-[#374151]" title={r.sales_executive}>
                  {r.sales_executive || "—"}
                </td>
                <td className="px-3 py-1.5 text-[#374151]">{fmtDate(r.submitted_date)}</td>
                <td className="px-3 py-1.5">
                  {r.end_date ? (
                    <span
                      className={`inline-block rounded-md px-2 py-0.5 text-[10px] font-semibold tabular-nums ${daysToEndClass(days)}`}
                      title={fmtDate(r.end_date)}
                    >
                      {fmtDate(r.end_date)}
                      {days != null && (
                        <span className="ml-1 opacity-80">
                          ({days < 0 ? `${days}d` : `+${days}d`})
                        </span>
                      )}
                    </span>
                  ) : (
                    <span className="text-[10px] text-[#9CA3AF]">—</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </TableShell>
      {total > pageSize && (
        <div className="mt-2 flex items-center justify-between text-xs text-[#6B7280]">
          <div>
            Page {page} / {lastPage} · {total.toLocaleString("en-US")} rows
          </div>
          <div className="flex gap-1">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page <= 1}
              className="rounded border border-[#E5E7EB] bg-white px-2 py-1 hover:bg-[#F9FAFB] disabled:opacity-40"
            >
              Prev
            </button>
            <button
              onClick={() => setPage(Math.min(lastPage, page + 1))}
              disabled={page >= lastPage}
              className="rounded border border-[#E5E7EB] bg-white px-2 py-1 hover:bg-[#F9FAFB] disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Generic helpers
// ---------------------------------------------------------------------------

function Panel({
  title,
  subtitle,
  children,
}: {
  title?: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border border-[#E5E7EB] bg-white p-4">
      {title && (
        <div className="mb-2 flex items-baseline justify-between">
          <div>
            <h3 className="text-sm font-semibold text-[#111827]">{title}</h3>
            {subtitle && (
              <div className="mt-0.5 text-[10px] text-[#6B7280]">{subtitle}</div>
            )}
          </div>
        </div>
      )}
      {children}
    </section>
  )
}

function TableShell({
  loading,
  empty,
  cols,
  children,
}: {
  loading: boolean
  empty: boolean
  cols: number
  children: React.ReactNode
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          {children}
          {loading && (
            <tbody>
              <tr>
                <td colSpan={cols} className="px-3 py-8 text-center text-[#6B7280]">
                  <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />
                  Loading…
                </td>
              </tr>
            </tbody>
          )}
          {!loading && empty && (
            <tbody>
              <tr>
                <td colSpan={cols} className="px-3 py-8 text-center text-[#6B7280]">
                  No rows match the current filters.
                </td>
              </tr>
            </tbody>
          )}
        </table>
      </div>
    </div>
  )
}

function SortableTh({
  label,
  k,
  altK,
  sort,
  setSort,
  numeric,
}: {
  label: string
  k: RfpDetailSort
  altK?: RfpDetailSort
  sort: RfpDetailSort
  setSort: (s: RfpDetailSort) => void
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
        {label} ↕
      </button>
    </th>
  )
}

// ---------------------------------------------------------------------------
// Filter pill (multi-select dropdown, pure HTML — no Base UI)
// ---------------------------------------------------------------------------

function FilterPill({
  label,
  options,
  selected,
  onChange,
  searchable,
}: {
  label: string
  options: string[]
  selected: string[]
  onChange: (next: string[]) => void
  searchable?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const filtered = useMemo(() => {
    if (!searchable || !query) return options
    const q = query.toLowerCase()
    return options.filter((o) => o.toLowerCase().includes(q))
  }, [options, query, searchable])
  const summary =
    selected.length === 0
      ? "All"
      : selected.length === 1
        ? selected[0]
        : `${selected.length} selected`

  return (
    <div className="relative">
      <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </label>
      <button
        onClick={() => setOpen((v) => !v)}
        className="mt-1 flex w-full items-center justify-between rounded-md border border-[#E5E7EB] bg-white px-3 py-1.5 text-xs text-[#374151] hover:bg-[#F9FAFB]"
      >
        <span className="max-w-[14rem] truncate">{summary}</span>
        <span className="text-[#6B7280]">▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute left-0 right-0 z-30 mt-1 max-h-64 overflow-auto rounded-md border border-[#E5E7EB] bg-white p-1 text-xs shadow-lg">
            {searchable && (
              <input
                type="text"
                placeholder="Search…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="mb-1 w-full rounded border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
              />
            )}
            <div className="flex items-center justify-between border-b border-[#F3F4F6] px-2 py-1">
              <span className="text-[10px] text-[#6B7280]">
                {selected.length} / {options.length}
              </span>
              <button
                onClick={() => onChange([])}
                className="rounded px-1.5 py-0.5 text-[10px] text-[#1B3A5C] hover:bg-[#F3F4F6]"
              >
                Clear
              </button>
            </div>
            {filtered.length === 0 && (
              <div className="px-2 py-2 text-[10px] text-[#6B7280]">No matches</div>
            )}
            {filtered.map((opt) => {
              const on = selected.includes(opt)
              return (
                <label
                  key={opt}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-[#F3F4F6]"
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() =>
                      onChange(
                        on ? selected.filter((s) => s !== opt) : [...selected, opt],
                      )
                    }
                    className="h-3 w-3"
                  />
                  <span className="flex-1 truncate">{opt}</span>
                </label>
              )
            })}
          </div>
        </>
      )}
      {selected.length > 0 && (
        <button
          onClick={() => onChange([])}
          className="absolute right-2 top-7 rounded-full bg-[#F3F4F6] p-0.5 text-[#6B7280] hover:bg-[#E5E7EB]"
          aria-label={`Clear ${label}`}
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Date range picker — YTD / MTD / Last Month / Last Quarter / Custom
// ---------------------------------------------------------------------------

function DateRange({
  from,
  to,
  ytdFrom,
  ytdTo,
  onChange,
}: {
  from: string | null
  to: string | null
  ytdFrom: string
  ytdTo: string
  onChange: (from: string | null, to: string | null) => void
}) {
  const [open, setOpen] = useState(false)

  const presets: Array<{ key: string; label: string; range: () => [string, string] }> = [
    { key: "ytd", label: "YTD", range: () => [ytdFrom, ytdTo] },
    {
      key: "mtd",
      label: "MTD",
      range: () => {
        const now = new Date()
        const y = now.getFullYear()
        const m = String(now.getMonth() + 1).padStart(2, "0")
        const d = String(now.getDate()).padStart(2, "0")
        return [`${y}-${m}-01`, `${y}-${m}-${d}`]
      },
    },
    {
      key: "last-month",
      label: "Last Month",
      range: () => {
        const now = new Date()
        const lastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1)
        const endLastMonth = new Date(now.getFullYear(), now.getMonth(), 0)
        return [iso(lastMonth), iso(endLastMonth)]
      },
    },
    {
      key: "last-quarter",
      label: "Last 90d",
      range: () => {
        const now = new Date()
        const ago = new Date(now.getTime() - 90 * 86400000)
        return [iso(ago), iso(now)]
      },
    },
  ]

  const current = `${from ?? ytdFrom} → ${to ?? ytdTo}`

  return (
    <div className="relative">
      <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        Select date range
      </label>
      <button
        onClick={() => setOpen((v) => !v)}
        className="mt-1 flex w-full items-center justify-between rounded-md border border-[#E5E7EB] bg-white px-3 py-1.5 text-xs text-[#374151] hover:bg-[#F9FAFB]"
      >
        <span className="max-w-[14rem] truncate">{current}</span>
        <span className="text-[#6B7280]">▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute left-0 z-30 mt-1 w-[280px] rounded-md border border-[#E5E7EB] bg-white p-2 text-xs shadow-lg">
            <div className="mb-2 flex flex-wrap gap-1">
              {presets.map((p) => (
                <button
                  key={p.key}
                  onClick={() => {
                    const [f, t] = p.range()
                    onChange(f, t)
                    setOpen(false)
                  }}
                  className="rounded border border-[#E5E7EB] bg-white px-2 py-1 hover:bg-[#F3F4F6]"
                >
                  {p.label}
                </button>
              ))}
            </div>
            <div className="space-y-1">
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
                From
              </label>
              <input
                type="date"
                value={from ?? ""}
                onChange={(e) => onChange(e.target.value || null, to)}
                className="w-full rounded border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
              />
              <label className="mt-1 block text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
                To
              </label>
              <input
                type="date"
                value={to ?? ""}
                onChange={(e) => onChange(from, e.target.value || null)}
                className="w-full rounded border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function iso(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

function parseList(v: string | null): string[] {
  if (!v) return []
  return v.split(",").map((x) => x.trim()).filter(Boolean)
}
