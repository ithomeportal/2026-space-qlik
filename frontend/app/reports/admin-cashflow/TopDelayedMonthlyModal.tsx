"use client"

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-08-24 "Aging Updates") R2 — the "Table" pop-up behind the
// "Top customers contributing to delays" card.
//
// Thirteen columns: Customer, then Late / Revenue / AVG Days across four
// DISCRETE months (this month, last month, two and three months back). The
// card behind it is one number per customer for the page's date range; this is
// the same customers read as a trend.
//
// The months are NOT derived here. `meta.buckets` names the month each of
// tm/lm/l2m/l3m stands for, so the header cannot drift from the numbers when
// the pop-up is left open across midnight on the 1st.
//
// Overlay is `UnbilledExpandModal` — a plain fixed div, React-18 safe, the
// same idiom every other pop-up in this report uses.
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { SortableTh, useSortable } from "@/components/SortableTable"
import {
  useTopDelayedCustomersMonthly,
  TOP_DELAYED_TABLE_KEYS,
  type AdminCashflowFilters,
  type TopDelayedBucket,
  type TopDelayedMonthlyRow,
  type TopDelayedTableKey,
} from "@/lib/admin-cashflow-api"

import { fmtCount, fmtNum1, fmtUsd, fmtUsdCompact } from "./format"
import { CustomerFilterLink, UnbilledExpandModal } from "./UnbilledShared"

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

/**
 * "2026-08-01" → "Aug 2026", parsed by hand.
 *
 * `new Date("2026-08-01")` is UTC midnight, which renders as the PREVIOUS
 * month for anyone west of Greenwich — the column would read "Jul" while its
 * numbers are August's.
 */
function monthLabel(iso: string | undefined): string {
  if (!iso) return ""
  const [y, m] = iso.split("-")
  const idx = Number(m) - 1
  return idx >= 0 && idx < 12 ? `${MONTHS[idx]} ${y}` : iso
}

// The TABLE's four months. The endpoint returns eight; the extra four exist
// only so the charts below can span eight off the same fetch, and must never
// leak into the table — see the endpoint docstring.
const KEYS: TopDelayedTableKey[] = [...TOP_DELAYED_TABLE_KEYS]
const SHORT: Record<TopDelayedTableKey, string> = {
  tm: "TM",
  lm: "LM",
  l2m: "L2M",
  l3m: "L3M",
}

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-08-27) R2 — three line charts beside the table.
//
// One line each, NOT one per customer: the ask is the monthly SUM of Late, the
// monthly SUM of Revenue and the AVERAGE of AVG Days, which are aggregates over
// the table's rows. With 78 customers live a line apiece would be unreadable
// anyway; to see a single customer, click its name and the page filter narrows
// every panel including this one.
//
// The customer set is the table's exactly — same rows, same qualifying rule —
// so the chart can never describe a universe the table behind it does not (§16).
// ---------------------------------------------------------------------------
type MetricView = "table" | "late" | "revenue" | "avg_days"

const METRIC_LABEL: Record<Exclude<MetricView, "table">, string> = {
  late: "Late",
  revenue: "Revenue",
  avg_days: "AVG Days",
}

const METRIC_COLOR: Record<Exclude<MetricView, "table">, string> = {
  late: "#B91C1C",
  revenue: "#1B3A5C",
  avg_days: "#B45309",
}

/**
 * Fold the per-customer rows into one point per bucket, oldest → newest.
 *
 * ⚠ AVG Days is weighted BY LOADS, not a mean of the per-customer averages —
 * an unweighted mean lets a customer with two loads outvote one with two
 * hundred. `loads_<key>` is emitted by the endpoint for exactly this.
 */
function buildSeries(
  rows: TopDelayedMonthlyRow[],
  buckets: TopDelayedBucket[],
) {
  // Oldest first so the line reads left → right; the payload is newest first.
  return buckets
    .slice()
    .reverse()
    .map((b) => {
      let late = 0
      let revenue = 0
      let daysSum = 0
      let loads = 0
      for (const r of rows) {
        late += (r[`late_${b.key}`] as number | null) ?? 0
        revenue += (r[`rev_${b.key}`] as number | null) ?? 0
        const avg = r[`avg_days_${b.key}`] as number | null
        const n = (r[`loads_${b.key}`] as number | null) ?? 0
        if (avg != null && n > 0) {
          daysSum += avg * n
          loads += n
        }
      }
      return {
        label: monthLabel(b.month),
        late,
        revenue,
        // null (not 0) when a bucket has no loads at all, so the line breaks
        // instead of dropping to a floor that reads as "zero days late".
        avg_days: loads > 0 ? daysSum / loads : null,
      }
    })
}

function MetricChart({
  metric,
  data,
}: {
  metric: Exclude<MetricView, "table">
  data: ReturnType<typeof buildSeries>
}) {
  const color = METRIC_COLOR[metric]
  const fmt =
    metric === "revenue"
      ? fmtUsd
      : metric === "avg_days"
        ? fmtNum1
        : fmtCount
  return (
    <ResponsiveContainer width="100%" height={380}>
      <LineChart data={data} margin={{ top: 20, right: 24, bottom: 0, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 11, fill: "#6B7280" }}
          tickLine={false}
          axisLine={{ stroke: "#E5E7EB" }}
        />
        <YAxis
          tick={{ fontSize: 11, fill: "#6B7280" }}
          tickLine={false}
          axisLine={false}
          width={metric === "revenue" ? 70 : 48}
          tickFormatter={(v: number) =>
            metric === "revenue" ? fmtUsdCompact(v) : String(v)
          }
        />
        <Tooltip
          formatter={(v: unknown) => [fmt(v as number), METRIC_LABEL[metric]]}
          contentStyle={{
            fontSize: 12,
            borderRadius: 8,
            border: "1px solid #E5E7EB",
          }}
        />
        <Line
          type="monotone"
          dataKey={metric}
          stroke={color}
          strokeWidth={2}
          dot={{ r: 3, fill: color }}
          // A bucket with no loads is a gap, not a zero.
          connectNulls={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}


export function TopDelayedMonthlyModal({
  filters,
  onClose,
  onCustomerClick,
}: {
  filters: AdminCashflowFilters
  onClose: () => void
  // Bruno (PDF 2026-08-27) R1: click a customer name to filter the page.
  onCustomerClick?: (name: string) => void
}) {
  const { data, isLoading } = useTopDelayedCustomersMonthly(filters, true)

  // Memoised because `?? []` mints a fresh array on every render, which would
  // make the buildSeries memo below recompute every time and defeat itself.
  const rows = useMemo(
    () => (data?.data ?? []) as TopDelayedMonthlyRow[],
    [data],
  )
  const buckets = useMemo(
    () => (data?.meta?.buckets ?? []) as TopDelayedBucket[],
    [data],
  )
  const labelFor = (k: TopDelayedTableKey) =>
    monthLabel(buckets.find((b) => b.key === k)?.month)

  // Money and counts lead with the biggest first; only the name starts ascending.
  const { sorted, ...sortState } = useSortable<TopDelayedMonthlyRow>(
    rows,
    "late_revenue_total",
    "desc",
    (key) => (key === "customer_name" ? "asc" : "desc"),
  )

  const total = data?.meta?.total ?? rows.length
  const truncated = data?.meta?.truncated === true

  // Bruno (PDF 2026-08-27) R2: Table (default) / Late / Revenue / AVG Days.
  const [view, setView] = useState<MetricView>("table")
  const series = useMemo(() => buildSeries(rows, buckets), [rows, buckets])

  return (
    <UnbilledExpandModal
      title="Top customers contributing to delays — by month"
      subtitle={
        buckets.length
          ? `Late = bill_date − dest_actual_departure > ${data?.meta?.late_days ?? 2} days · ` +
            `customers averaging ≥ ${data?.meta?.min_avg_days ?? 2} days · ` +
            (view === "table"
              ? KEYS.map((k) => `${SHORT[k]} = ${labelFor(k)}`).join(" · ")
              : `${METRIC_LABEL[view]} across ${series.length} months, all ${
                  rows.length
                } customer${rows.length === 1 ? "" : "s"} combined`)
          : "Late = bill_date − dest_actual_departure > 2 days"
      }
      onClose={onClose}
      wide
    >
      {isLoading ? (
        <div className="flex h-40 items-center justify-center text-[#6B7280]">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : rows.length === 0 ? (
        <div className="py-12 text-center text-xs text-[#9CA3AF]">
          No customers with delays in the last four months for these filters
        </div>
      ) : (
        <>
          {/* Bruno (PDF 2026-08-27) R2: Table / Late / Revenue / AVG Days. */}
          <div className="mb-3 flex items-center justify-end">
            <div className="inline-flex overflow-hidden rounded-md border border-[#E5E7EB]">
              {(["table", "late", "revenue", "avg_days"] as MetricView[]).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={`px-2.5 py-1 text-[11px] ${
                    view === v
                      ? "bg-[#1B3A5C] text-white"
                      : "bg-white text-[#6B7280] hover:bg-[#F3F4F6]"
                  }`}
                >
                  {v === "table" ? "Table" : METRIC_LABEL[v]}
                </button>
              ))}
            </div>
          </div>

          {view !== "table" ? (
            <MetricChart metric={view} data={series} />
          ) : (
          <div className="overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[10px] uppercase tracking-wider text-[#6B7280]">
                <tr className="border-b border-[#E5E7EB]">
                  <SortableTh label="Customer" columnKey="customer_name" state={sortState} />
                  {KEYS.map((k) => (
                    <SortableTh
                      key={`late_${k}`}
                      label={`Late ${SHORT[k]}`}
                      columnKey={`late_${k}`}
                      state={sortState}
                      align="right"
                      className={k === "tm" ? "border-l border-[#E5E7EB]" : ""}
                    />
                  ))}
                  {KEYS.map((k) => (
                    <SortableTh
                      key={`rev_${k}`}
                      label={`Rev ${SHORT[k]}`}
                      columnKey={`rev_${k}`}
                      state={sortState}
                      align="right"
                      className={k === "tm" ? "border-l border-[#E5E7EB]" : ""}
                    />
                  ))}
                  {KEYS.map((k) => (
                    <SortableTh
                      key={`avg_days_${k}`}
                      label={`AVG Days ${SHORT[k]}`}
                      columnKey={`avg_days_${k}`}
                      state={sortState}
                      align="right"
                      className={k === "tm" ? "border-l border-[#E5E7EB]" : ""}
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => (
                  <tr key={r.customer_name} className="border-b border-[#F3F4F6] last:border-0">
                    <td className="max-w-[280px] truncate px-3 py-1.5" title={r.customer_name}>
                      <CustomerFilterLink
                        name={r.customer_name}
                        onClick={onCustomerClick}
                        className="block max-w-full truncate"
                      />
                    </td>
                    {KEYS.map((k) => (
                      <td
                        key={`late_${k}`}
                        className={`px-3 py-1.5 text-right tabular-nums ${
                          k === "tm" ? "border-l border-[#F3F4F6]" : ""
                        }`}
                      >
                        {fmtCount(r[`late_${k}`] as number | null)}
                      </td>
                    ))}
                    {KEYS.map((k) => (
                      <td
                        key={`rev_${k}`}
                        className={`px-3 py-1.5 text-right font-semibold tabular-nums text-[#991B1B] ${
                          k === "tm" ? "border-l border-[#F3F4F6]" : ""
                        }`}
                      >
                        {fmtUsd(r[`rev_${k}`] as number | null)}
                      </td>
                    ))}
                    {KEYS.map((k) => (
                      <td
                        key={`avg_days_${k}`}
                        className={`px-3 py-1.5 text-right tabular-nums ${
                          k === "tm" ? "border-l border-[#F3F4F6]" : ""
                        }`}
                      >
                        {fmtNum1(r[`avg_days_${k}`] as number | null)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          )}
          {/* A worklist that drops rows must say so. */}
          <div className="border-t border-[#E5E7EB] px-3 py-2 text-[10px] text-[#6B7280]">
            {truncated
              ? `Showing ${sorted.length} of ${total} customers (largest $ at risk first)`
              : `${total} customer${total === 1 ? "" : "s"}`}
          </div>
        </>
      )}
    </UnbilledExpandModal>
  )
}
