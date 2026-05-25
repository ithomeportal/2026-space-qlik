"use client"

import { Loader2 } from "lucide-react"
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
  useAttritionLosses,
  type AttritionFilters,
  type LossPoint,
  type LossTotals,
  type NegCustomerRow,
  type WorstLaneRow,
} from "@/lib/attrition-wow-api"
import { SortableTh, useSortable } from "../../ceo-executive/sortable"
import { AttritionErrorBanner } from "../ErrorBanner"
import { fmtCount, fmtPct, fmtUsd } from "../format"

interface Props {
  filters: AttritionFilters
  // "Client" under the RUAN view (page 6), "Customer" otherwise.
  entityLabel: string
}

// Recharts v3 types formatters loosely — keep callbacks unannotated and coerce
// with Number(...) at the call site (this repo's established build-safe pattern).
const fmtKAxis = (v: number) => {
  if (v === 0) return "0"
  const k = v / 1000
  return Math.abs(k) >= 1 ? `${Math.round(k)}k` : `${v}`
}

export function LossesTab({ filters, entityLabel }: Props) {
  const { data: res, isLoading, error } = useAttritionLosses(filters)
  const d = res?.data

  const months = (d?.by_month ?? []).map((p) => ({ ...p, label: fmtMonth(p.bucket) }))
  const weeks = (d?.by_week ?? []).map((p) => ({ ...p, label: fmtWeekDay(p.bucket) }))

  if (isLoading && !d) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <AttritionErrorBanner errors={[error]} label="Losses" />

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <LossChart title="Losses by Month" subtitle="Last 8 months" data={months} />
        <LossChart title="Losses by Week" subtitle="Last 8 weeks" data={weeks} />
      </section>

      <WorstLanesTable
        rows={d?.worst_lanes ?? []}
        totals={d?.totals.lanes}
        entityLabel={entityLabel}
      />

      <NegCustomersTable
        rows={d?.by_customer ?? []}
        totals={d?.totals.customers}
        entityLabel={entityLabel}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Combo chart: red bars = Σ negative profit (negative ⇒ bars drop below 0),
// blue line = # negative loads on the right axis.
// ---------------------------------------------------------------------------

function LossChart({
  title,
  subtitle,
  data,
}: {
  title: string
  subtitle: string
  data: (LossPoint & { label: string })[]
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="border-b border-[#F3F4F6] px-4 py-2">
        <div className="text-sm font-semibold text-[#1B3A5C]">{title}</div>
        <div className="text-[11px] text-[#6B7280]">{subtitle}</div>
      </div>
      <div className="p-3">
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={data} margin={{ top: 12, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} />
            <YAxis yAxisId="left" tickFormatter={fmtKAxis} tick={{ fontSize: 11 }} />
            <YAxis
              yAxisId="right"
              orientation="right"
              allowDecimals={false}
              tick={{ fontSize: 11 }}
            />
            <Tooltip
              formatter={(v, name) =>
                name === "$ Profit (negative)" ? fmtUsd(Number(v)) : fmtCount(Number(v))
              }
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar
              yAxisId="left"
              dataKey="neg_profit"
              fill="#DC2626"
              name="$ Profit (negative)"
              barSize={28}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="neg_loads"
              stroke="#1D4ED8"
              name="# Loads"
              dot={{ r: 3 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Worst Margins by Lane — totals row pinned at the top, every column sortable.
// ---------------------------------------------------------------------------

function WorstLanesTable({
  rows,
  totals,
  entityLabel,
}: {
  rows: WorstLaneRow[]
  totals: LossTotals | undefined
  entityLabel: string
}) {
  const { sorted, sortKey, sortDir, toggle } = useSortable<WorstLaneRow>(
    rows,
    "profit",
    "asc",
  )

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="border-b border-[#FECACA] bg-[#FEF2F2] px-4 py-2 text-sm font-semibold text-[#991B1B]">
        Worst Margins by Lane{" "}
        <span className="font-normal text-[#B91C1C]">· negative-margin loads</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[920px] text-[11px]">
          <thead className="bg-[#FEF2F2] text-[10px] uppercase tracking-wider text-[#991B1B]">
            <tr>
              <SortableTh<WorstLaneRow> columnKey="customer" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">{entityLabel}</SortableTh>
              <SortableTh<WorstLaneRow> columnKey="origin" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Origin</SortableTh>
              <SortableTh<WorstLaneRow> columnKey="dest" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Destination</SortableTh>
              <SortableTh<WorstLaneRow> columnKey="loads" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}># Loads</SortableTh>
              <SortableTh<WorstLaneRow> columnKey="revenue" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Revenue</SortableTh>
              <SortableTh<WorstLaneRow> columnKey="profit" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Profit</SortableTh>
              <SortableTh<WorstLaneRow> columnKey="margin" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Margin %</SortableTh>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            <TotalsRow totals={totals} cols={3} label="Totals" />
            {sorted.map((r, i) => (
              <tr key={`${r.customer}-${r.origin}-${r.dest}-${i}`} className="hover:bg-[#FAFAFA]">
                <td className="px-3 py-1.5 max-w-[240px] truncate" title={r.customer ?? ""}>{r.customer || "—"}</td>
                <td className="px-3 py-1.5 text-[#374151]">{r.origin || "—"}</td>
                <td className="px-3 py-1.5 text-[#374151]">{r.dest || "—"}</td>
                <td className="px-3 py-1.5 text-right font-mono">{fmtCount(r.loads)}</td>
                <td className="px-3 py-1.5 text-right font-mono">{fmtUsd(r.revenue)}</td>
                <td className="px-3 py-1.5 text-right font-mono text-[#DC2626]">{fmtUsd(r.profit)}</td>
                <td className="px-3 py-1.5 text-right font-mono text-[#DC2626]">{fmtPct(r.margin)}</td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={7} className="py-8 text-center text-xs text-[#9CA3AF]">
                  No negative-margin loads in scope.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Negative Loads — By Customer (or Client) — totals at top, sortable.
// ---------------------------------------------------------------------------

function NegCustomersTable({
  rows,
  totals,
  entityLabel,
}: {
  rows: NegCustomerRow[]
  totals: LossTotals | undefined
  entityLabel: string
}) {
  const { sorted, sortKey, sortDir, toggle } = useSortable<NegCustomerRow>(
    rows,
    "profit",
    "asc",
  )

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="border-b border-[#FECACA] bg-[#FEF2F2] px-4 py-2 text-sm font-semibold text-[#991B1B]">
        Negative Loads — by {entityLabel}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[11px]">
          <thead className="bg-[#FEF2F2] text-[10px] uppercase tracking-wider text-[#991B1B]">
            <tr>
              <SortableTh<NegCustomerRow> columnKey="customer" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">{entityLabel}</SortableTh>
              <SortableTh<NegCustomerRow> columnKey="loads" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}># Loads</SortableTh>
              <SortableTh<NegCustomerRow> columnKey="revenue" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Revenue</SortableTh>
              <SortableTh<NegCustomerRow> columnKey="profit" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Profit</SortableTh>
              <SortableTh<NegCustomerRow> columnKey="margin" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Margin %</SortableTh>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            <TotalsRow totals={totals} cols={1} label="Totals" />
            {sorted.map((r, i) => (
              <tr key={`${r.customer}-${i}`} className="hover:bg-[#FAFAFA]">
                <td className="px-3 py-1.5 max-w-[320px] truncate" title={r.customer ?? ""}>{r.customer || "—"}</td>
                <td className="px-3 py-1.5 text-right font-mono">{fmtCount(r.loads)}</td>
                <td className="px-3 py-1.5 text-right font-mono">{fmtUsd(r.revenue)}</td>
                <td className="px-3 py-1.5 text-right font-mono text-[#DC2626]">{fmtUsd(r.profit)}</td>
                <td className="px-3 py-1.5 text-right font-mono text-[#DC2626]">{fmtPct(r.margin)}</td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={5} className="py-8 text-center text-xs text-[#9CA3AF]">
                  No negative-margin loads in scope.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// Pinned totals row. `cols` = number of leading text columns to span with the
// "Totals" label before the numeric block (3 for lanes, 1 for customers).
function TotalsRow({
  totals,
  cols,
  label,
}: {
  totals: LossTotals | undefined
  cols: number
  label: string
}) {
  return (
    <tr className="border-b-2 border-[#991B1B] bg-[#FEF2F2] font-semibold text-[#991B1B]">
      <td colSpan={cols} className="px-3 py-2 text-[10px] uppercase tracking-wider">
        {label}
      </td>
      <td className="px-3 py-2 text-right font-mono">{totals ? fmtCount(totals.loads) : "—"}</td>
      <td className="px-3 py-2 text-right font-mono">{totals ? fmtUsd(totals.revenue) : "—"}</td>
      <td className="px-3 py-2 text-right font-mono text-[#DC2626]">{totals ? fmtUsd(totals.profit) : "—"}</td>
      <td className="px-3 py-2 text-right font-mono text-[#DC2626]">{totals ? fmtPct(totals.margin) : "—"}</td>
    </tr>
  )
}

function fmtMonth(iso: string): string {
  try {
    return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
      month: "short",
      year: "2-digit",
    })
  } catch {
    return iso
  }
}

function fmtWeekDay(iso: string): string {
  try {
    return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    })
  } catch {
    return iso
  }
}
