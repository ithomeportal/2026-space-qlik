"use client"

import { Loader2 } from "lucide-react"
import {
  useAttritionCustomerAttrition,
  useAttritionSummary,
  useAttritionTrends,
  useAttritionWowVariation,
  type AttritionFilters,
  type CountBlock,
  type DiffPair,
  type MetricBlock,
} from "@/lib/attrition-wow-api"
import { CustomerAttritionChart } from "./CustomerAttritionChart"
import { AttritionErrorBanner } from "../ErrorBanner"
import {
  fmtCount,
  fmtCount1,
  fmtPct,
  fmtSignedCount,
  fmtSignedPct,
  fmtSignedPctInverted,
  fmtSignedUsd,
  fmtUsd,
  fmtWeekRange,
} from "../format"
import { BarPanel } from "./BarPanel"

// Cream tint applied to the L8W avg column (Bruno's request, 2026-04-27).
const L8W_BG = "bg-[#FFFBEB]"
// Bruno round-3 (2026-05-07): light blue for the L2W comparison cluster,
// light green for the LW cluster — picks up which window each column belongs
// to at a glance without reading the headers.
const L2W_BG = "bg-[#EFF6FF]"
const LW_BG = "bg-[#ECFDF5]"

interface Props {
  filters: AttritionFilters
  entityLabel: string
}

export function OverviewTab({ filters, entityLabel }: Props) {
  const { data: summaryRes, isLoading: loadingSummary, error: summaryErr } =
    useAttritionSummary(filters)
  const { data: wowRes, isLoading: loadingWow, error: wowErr } =
    useAttritionWowVariation(filters)
  const { data: trendsRes, isLoading: loadingTrends, error: trendsErr } =
    useAttritionTrends(filters, 15)
  const { data: custAttrRes, isLoading: loadingCustAttr, error: custAttrErr } =
    useAttritionCustomerAttrition(filters, 15)
  const s = summaryRes?.data
  const w = wowRes?.data
  const t = trendsRes?.data
  const ca = custAttrRes?.data

  return (
    <div className="space-y-6">
      <AttritionErrorBanner
        errors={[summaryErr, wowErr, trendsErr, custAttrErr]}
        label="Overview"
      />

      {/* Window labels */}
      {s && (
        <div className="flex flex-wrap gap-3 text-[11px] text-[#6B7280]">
          <Badge label="Last 8 Weeks" range={s.windows.l8w} />
          <Badge label="Last Week" range={s.windows.lw} />
          <Badge label="Last 2 Weeks" range={s.windows.l2w} />
        </div>
      )}

      {/* Active Lanes / Active Customers */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ActiveCard
          title="Lane Attrition"
          accent="text-[#1B3A5C]"
          loading={loadingSummary}
          block={s?.active_lanes}
        />
        <ActiveCard
          title={`${entityLabel} Attrition`}
          accent="text-[#1B3A5C]"
          loading={loadingSummary}
          block={s?.active_customers}
        />
      </div>

      {/* Metric grid: # Loads, $ Revenue, $ Profit, % Margin, $/Load */}
      <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-[#F9FAFB] text-[10px] text-[#6B7280]">
            <tr>
              <th className="w-32 px-3 py-2 text-left font-semibold uppercase tracking-wider">
                Metric
              </th>
              <th
                className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${L8W_BG}`}
              >
                L8W avg
              </th>
              <th
                className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${L2W_BG}`}
              >
                L2W avg
              </th>
              <th
                className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${L2W_BG}`}
              >
                Δ (L2W vs L8W)
              </th>
              <th
                className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${L2W_BG}`}
              >
                % (L2W vs L8W)
              </th>
              <th
                className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${LW_BG}`}
              >
                Last Week
              </th>
              <th
                className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${LW_BG}`}
              >
                Δ (LW vs L8W)
              </th>
              <th
                className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${LW_BG}`}
              >
                % (LW vs L8W)
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            <MetricRow
              label="# Loads"
              loading={loadingSummary}
              block={s?.loads}
              fmt={fmtCount}
              avgFmt={fmtCount1}
              isCount
            />
            <MetricRow
              label="$ Revenue"
              loading={loadingSummary}
              block={s?.revenue}
              fmt={fmtUsd}
            />
            <MetricRow
              label="$ Profit"
              loading={loadingSummary}
              block={s?.profit}
              fmt={fmtUsd}
            />
            <MetricRow
              label="% Margin"
              loading={loadingSummary}
              block={s?.margin_pct}
              fmt={fmtPct}
              isPct
            />
            <MetricRow
              label="$ Profit per Load"
              loading={loadingSummary}
              block={s?.profit_per_load}
              fmt={fmtUsd}
            />
          </tbody>
        </table>
      </div>

      {/* Bruno round-3 (2026-05-07): duplicate # Loads by Week + # Customers
          by Week from Trends & Pivots so the headline cadence sits next to
          the KPI table without a tab change. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {loadingTrends && !t ? (
          <div className="col-span-full flex h-48 items-center justify-center rounded-xl border border-[#E5E7EB] bg-white">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : (
          <>
            <BarPanel
              title="Weekly Loads"
              data={t?.weeks ?? []}
              field="loads"
              fmt={fmtCount}
              color="#DC2626"
              axisColor="#DC2626"
              isPct={false}
              refValue={t?.reference?.l8w_avg_loads ?? null}
              refFmt={fmtCount1}
            />
            <BarPanel
              title="Weekly Customers"
              data={t?.weeks ?? []}
              field="customers"
              fmt={fmtCount}
              color="#0891B2"
              axisColor="#0891B2"
              isPct={false}
              /* Bruno 2026-08-03: this legend is the reference the CUSTOMER
                 ATTRITION card's L8W must match, so both render 1 decimal. */
              refValue={t?.reference?.l8w_avg_customers ?? null}
              refFmt={fmtCount1}
            />
          </>
        )}
      </div>

      {/* Bruno 2026-06-11 (Request 1): Customer Attrition line — 15-week
          weekly ratio, displayed right after the Weekly Loads / Weekly
          Customers charts. */}
      {loadingCustAttr && !ca ? (
        <div className="flex h-48 items-center justify-center rounded-xl border border-[#E5E7EB] bg-white">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <CustomerAttritionChart
          data={ca?.weeks ?? []}
          /* One customer ⇒ the ratio degenerates into shipping frequency; the
             chart explains itself instead of plotting ±700% spikes. */
          singleCustomer={Boolean(filters.customer)}
        />
      )}

      {/* WoW Total $Var headline + by-team line */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="rounded-xl border-2 border-[#FBBF24] bg-white p-6 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-[#6B7280]">
            Total 1-Week $Var
          </div>
          <div className="mt-1 text-[10px] text-[#9CA3AF]">
            (LW Profit − LW-1 Profit, summed across scope)
          </div>
          <div
            className={`mt-3 text-4xl font-bold ${
              w === undefined
                ? "text-[#6B7280]"
                : w.total >= 0
                  ? "text-[#15803D]"
                  : "text-[#DC2626]"
            }`}
          >
            {loadingWow
              ? "—"
              : w === undefined
                ? "—"
                : `${w.total >= 0 ? "+" : ""}${fmtUsd(w.total)}`}
          </div>
          {w?.windows && (
            <div className="mt-2 text-[10px] text-[#6B7280]">
              {fmtWeekRange(w.windows.lw_prev.start, w.windows.lw_prev.end)} →{" "}
              {fmtWeekRange(w.windows.lw.start, w.windows.lw.end)}
            </div>
          )}
        </div>

        <div className="lg:col-span-2 rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[#6B7280]">
            $Var by Team
          </div>
          {loadingWow ? (
            <div className="flex h-32 items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
            </div>
          ) : !w || w.by_team.length === 0 ? (
            <div className="py-8 text-center text-xs text-[#6B7280]">
              No teams in scope
            </div>
          ) : (
            <TeamBarChart data={w.by_team} />
          )}
        </div>
      </div>
    </div>
  )
}

function Badge({ label, range }: { label: string; range: { start: string; end: string } }) {
  return (
    <span className="rounded-full bg-[#F3F4F6] px-3 py-1 text-[#374151]">
      <strong>{label}:</strong>&nbsp;{fmtWeekRange(range.start, range.end)}
    </span>
  )
}

function ActiveCard({
  title,
  accent,
  loading,
  block,
}: {
  title: string
  accent: string
  loading: boolean
  block: CountBlock | undefined
}) {
  const diff = block?.diff ?? null
  const pct = block?.pct ?? null
  const sd = fmtSignedCount(diff)
  // Bruno R13 (2026-07-01): % Δ = (L8W − LW)/L8W with inverted colours
  // (positive attrition = red). The backend already flips the numerator; the
  // Δ (LW − L8W) count column keeps standard up=green colouring.
  const sp = fmtSignedPctInverted(pct)
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {title}
      </div>
      <div className="mt-3 grid grid-cols-4 gap-2">
        <CountCell
          label="L8W"
          value={loading ? "—" : fmtCount1(block?.l8w)}
          accent={accent}
        />
        <CountCell
          label="LW"
          value={loading ? "—" : fmtCount(block?.lw)}
          accent={accent}
        />
        <CountCell
          label="Δ (LW − L8W)"
          value={loading ? "—" : sd.text}
          accent={sd.className}
        />
        <CountCell
          label="% Δ"
          value={loading ? "—" : sp.text}
          accent={sp.className}
        />
      </div>
    </div>
  )
}

function CountCell({
  label,
  value,
  accent,
}: {
  label: string
  value: string
  accent: string
}) {
  return (
    <div className="rounded-md border border-[#F3F4F6] bg-[#F9FAFB] p-2">
      <div className="text-[9px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className={`mt-1 text-xl font-semibold ${accent}`}>{value}</div>
    </div>
  )
}

function MetricRow({
  label,
  loading,
  block,
  fmt,
  avgFmt,
  isCount,
  isPct,
}: {
  label: string
  loading: boolean
  block: MetricBlock | undefined
  fmt: (v: number | null | undefined) => string
  // Bruno Attrition R (PDF 2026-07-13): the # Loads row shows its L8W-avg and
  // L2W-avg cells with one decimal place, while LW and the Δ columns stay
  // integer. Defaults to `fmt` so every other row is unchanged.
  avgFmt?: (v: number | null | undefined) => string
  isCount?: boolean
  isPct?: boolean
}) {
  const cell = (v: number | null | undefined) => (loading ? "—" : fmt(v))
  const cellAvg = (v: number | null | undefined) =>
    loading ? "—" : (avgFmt ?? fmt)(v)
  const renderDiff = (d: DiffPair | undefined) => {
    if (!d) return { abs: "—", pct: "—", absCls: "text-[#6B7280]", pctCls: "text-[#6B7280]" }
    if (isPct) {
      // For margin pct, the "diff" is a delta of fractions; render as pp.
      const absText =
        d.diff === null
          ? "—"
          : `${d.diff >= 0 ? "+" : ""}${(d.diff * 100).toFixed(2)}pp`
      const cls =
        d.diff === null
          ? "text-[#6B7280]"
          : d.diff > 0
            ? "text-[#15803D]"
            : d.diff < 0
              ? "text-[#DC2626]"
              : "text-[#B45309]"
      const sp = fmtSignedPct(d.pct)
      return { abs: absText, pct: sp.text, absCls: cls, pctCls: sp.className }
    }
    const sa = isCount ? fmtSignedCount(d.diff) : fmtSignedUsd(d.diff)
    const sp = fmtSignedPct(d.pct)
    return { abs: sa.text, pct: sp.text, absCls: sa.className, pctCls: sp.className }
  }
  const lwDiff = renderDiff(block?.diff_lw_vs_l8w)
  const l2wDiff = renderDiff(block?.diff_l2w_vs_l8w)

  return (
    <tr>
      <td className="px-3 py-2.5 text-left text-xs font-semibold text-[#374151]">
        {label}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base text-[#111827] ${L8W_BG}`}>
        {cellAvg(block?.l8w_avg)}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base text-[#111827] ${L2W_BG}`}>
        {cellAvg(block?.l2w_avg)}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base ${L2W_BG} ${l2wDiff.absCls}`}>
        {l2wDiff.abs}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base ${L2W_BG} ${l2wDiff.pctCls}`}>
        {l2wDiff.pct}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base text-[#111827] ${LW_BG}`}>
        {cell(block?.lw)}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base ${LW_BG} ${lwDiff.absCls}`}>
        {lwDiff.abs}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base ${LW_BG} ${lwDiff.pctCls}`}>
        {lwDiff.pct}
      </td>
    </tr>
  )
}

function TeamBarChart({ data }: { data: { team: string; var: number }[] }) {
  const max = Math.max(0, ...data.map((d) => Math.abs(d.var)))
  if (max === 0) {
    return (
      <div className="py-8 text-center text-xs text-[#6B7280]">
        No variation across teams.
      </div>
    )
  }
  return (
    <div className="space-y-1.5">
      {data.map((d) => {
        const wPct = (Math.abs(d.var) / max) * 100
        const positive = d.var >= 0
        return (
          <div key={d.team} className="flex items-center gap-2">
            <div className="w-20 text-right font-mono text-[10px] text-[#374151]">
              {d.team || "—"}
            </div>
            <div className="relative flex-1 h-5 rounded bg-[#F3F4F6]">
              <div
                className={`absolute top-0 h-full rounded ${positive ? "bg-[#15803D]" : "bg-[#DC2626]"}`}
                style={{ width: `${wPct}%`, left: 0 }}
              />
            </div>
            <div
              className={`w-24 text-right font-mono text-xs ${positive ? "text-[#15803D]" : "text-[#DC2626]"}`}
            >
              {positive ? "+" : ""}
              {fmtUsd(d.var)}
            </div>
          </div>
        )
      })}
    </div>
  )
}
