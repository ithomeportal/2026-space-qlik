"use client"

import { Loader2 } from "lucide-react"
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useXrayDfwRisk,
  type XrayDfwFilters,
} from "@/lib/xray-dfw-api"
import { useSortable, SortableTh } from "@/components/SortableTable"
import { XrayDfwErrorBanner } from "../ErrorBanner"

interface Props {
  filters: XrayDfwFilters
  entityLabel?: string
  onCustomerClick?: (name: string) => void
  onLaneClick?: (lane: string) => void
}

const fmtKAxis = (v: number) => {
  if (v === 0) return "0"
  const k = v / 1000
  return Math.abs(k) >= 1 ? `${Math.round(k)}k` : `${v}`
}

// Bruno 2026-06-03 layout: Losses charts FIRST, then the tables in the order
// Negative Loads by Customer → Worst Margins by Lane → Negative Loads by
// Order, each with a server-side full-universe Totals row pinned at the top.
export function Risk({
  filters,
  entityLabel = "Customer",
  onCustomerClick,
  onLaneClick,
}: Props) {
  const { data, isLoading, error } = useXrayDfwRisk(filters)
  const r = data?.data

  const worstSort = useSortable(r?.worst_lanes ?? [])
  const negOrderSort = useSortable(r?.neg_orders ?? [])
  const negCustSort = useSortable(r?.neg_customers ?? [])
  const negTot = r?.totals?.neg
  const wlTot = r?.totals?.worst_lanes

  const fmtBucket = (s: string) => {
    const d = new Date(s)
    if (Number.isNaN(d.getTime())) return s
    return `${d.toLocaleString("en-US", { month: "short" })} ${String(d.getDate()).padStart(2, "0")}`
  }

  return (
    <div className="space-y-6">
      <XrayDfwErrorBanner label="Risk" errors={[error]} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Losses by Month" subtitle="Last 8 months" loading={isLoading}>
          <LossesChart data={[...(r?.losses_month ?? [])].reverse()} fmtBucket={fmtBucket} />
        </ChartCard>
        <ChartCard title="Losses by Week" subtitle="Last 8 weeks" loading={isLoading}>
          <LossesChart data={[...(r?.losses_week ?? [])].reverse()} fmtBucket={fmtBucket} />
        </ChartCard>
      </div>

      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#FCA5A5] bg-[#FEE2E2] px-3 py-2 text-sm font-semibold text-[#991B1B]">
          Negative Loads — by {entityLabel}
        </div>
        {isLoading ? (
          <Spin />
        ) : (
          <div className="max-h-[400px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#FEE2E2] text-[#6B7280]">
                <tr>
                  <SortableTh label={entityLabel} columnKey="customer" state={negCustSort} />
                  <SortableTh label="# Loads" columnKey="loads" state={negCustSort} align="right" />
                  <SortableTh label="$ Revenue" columnKey="revenue" state={negCustSort} align="right" />
                  <SortableTh label="$ Profit" columnKey="profit" state={negCustSort} align="right" />
                  <SortableTh label="Conc %" columnKey="conc_pct" state={negCustSort} align="right" />
                </tr>
              </thead>
              <tbody>
                {negTot && (
                  <tr className="sticky top-[29px] z-10 bg-[#FECACA] font-semibold">
                    <td className="px-3 py-1.5">Totals</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(negTot.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(negTot.revenue)}</td>
                    <td className="px-3 py-1.5 text-right text-[#991B1B]">{fmtUsd(negTot.profit)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(100)}</td>
                  </tr>
                )}
                {negCustSort.sorted.map((row, i) => (
                  <tr key={i} className="border-t border-[#FECACA] hover:bg-[#FEF2F2]">
                    <td className="px-3 py-1.5">
                      <ClickName value={row.customer} onClick={onCustomerClick} />
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(row.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.revenue)}</td>
                    <td className="px-3 py-1.5 text-right text-[#DC2626]">{fmtUsd(row.profit)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(row.conc_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#FCA5A5] bg-[#FEE2E2] px-3 py-2 text-sm font-semibold text-[#991B1B]">
          Worst Margins by Lane
        </div>
        {isLoading ? (
          <Spin />
        ) : (
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#FEE2E2] text-[#6B7280]">
                <tr>
                  <SortableTh label={entityLabel} columnKey="customer" state={worstSort} />
                  <SortableTh label="Origin" columnKey="origin" state={worstSort} />
                  <SortableTh label="Destination" columnKey="destination" state={worstSort} />
                  <SortableTh label="# Loads" columnKey="loads" state={worstSort} align="right" />
                  <SortableTh label="$ Revenue" columnKey="revenue" state={worstSort} align="right" />
                  <SortableTh label="$ Profit" columnKey="profit" state={worstSort} align="right" />
                  <SortableTh label="Margin %" columnKey="margin_pct" state={worstSort} align="right" />
                  <SortableTh label="Diff to 15%" columnKey="diff_15" state={worstSort} align="right" />
                  <SortableTh label="Diff to 18%" columnKey="diff_18" state={worstSort} align="right" />
                  <SortableTh label="Diff to 20%" columnKey="diff_20" state={worstSort} align="right" />
                </tr>
              </thead>
              <tbody>
                {wlTot && (
                  <tr className="sticky top-[29px] z-10 bg-[#FECACA] font-semibold">
                    <td className="px-3 py-1.5" colSpan={3}>Totals</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(wlTot.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(wlTot.revenue)}</td>
                    <td className="px-3 py-1.5 text-right text-[#991B1B]">{fmtUsd(wlTot.profit)}</td>
                    <td className="px-3 py-1.5 text-right text-[#991B1B]">{fmtPct(wlTot.margin_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(wlTot.diff_15)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(wlTot.diff_18)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(wlTot.diff_20)}</td>
                  </tr>
                )}
                {worstSort.sorted.map((row, i) => (
                  <tr key={i} className="border-t border-[#FECACA] hover:bg-[#FEF2F2]">
                    <td className="px-3 py-1.5">
                      <ClickName value={row.customer} onClick={onCustomerClick} />
                    </td>
                    <td className="px-3 py-1.5">{row.origin}</td>
                    <td className="px-3 py-1.5">
                      <ClickName
                        value={`${row.origin} - ${row.destination}`}
                        display={row.destination}
                        onClick={onLaneClick}
                      />
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(row.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.revenue)}</td>
                    <td className="px-3 py-1.5 text-right text-[#DC2626]">{fmtUsd(row.profit)}</td>
                    <td className="px-3 py-1.5 text-right text-[#DC2626]">{fmtPct(row.margin_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.diff_15)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.diff_18)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.diff_20)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#FCA5A5] bg-[#FEE2E2] px-3 py-2 text-sm font-semibold text-[#991B1B]">
          Negative Loads — by Order
        </div>
        {isLoading ? (
          <Spin />
        ) : (
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#FEE2E2] text-[#6B7280]">
                <tr>
                  <SortableTh label="Order" columnKey="id" state={negOrderSort} />
                  <SortableTh label={entityLabel} columnKey="customer" state={negOrderSort} />
                  <SortableTh label="Carrier" columnKey="carrier" state={negOrderSort} />
                  <SortableTh label="Origin" columnKey="origin" state={negOrderSort} />
                  <SortableTh label="Destination" columnKey="destination" state={negOrderSort} />
                  <SortableTh label="$ Revenue" columnKey="revenue" state={negOrderSort} align="right" />
                  <SortableTh label="$ Profit" columnKey="profit" state={negOrderSort} align="right" />
                  <SortableTh label="Margin %" columnKey="margin_pct" state={negOrderSort} align="right" />
                  <SortableTh label="Conc %" columnKey="conc_pct" state={negOrderSort} align="right" />
                </tr>
              </thead>
              <tbody>
                {negTot && (
                  <tr className="sticky top-[29px] z-10 bg-[#FECACA] font-semibold">
                    <td className="px-3 py-1.5" colSpan={5}>Totals ({fmtCount(negTot.loads)})</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(negTot.revenue)}</td>
                    <td className="px-3 py-1.5 text-right text-[#991B1B]">{fmtUsd(negTot.profit)}</td>
                    <td className="px-3 py-1.5 text-right text-[#991B1B]">{fmtPct(negTot.margin_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(100)}</td>
                  </tr>
                )}
                {negOrderSort.sorted.map((row) => (
                  <tr key={row.id} className="border-t border-[#FECACA] hover:bg-[#FEF2F2]">
                    <td className="px-3 py-1.5">{row.id}</td>
                    <td className="px-3 py-1.5">
                      <ClickName value={row.customer} onClick={onCustomerClick} />
                    </td>
                    <td className="px-3 py-1.5">{row.carrier}</td>
                    <td className="px-3 py-1.5">{row.origin}</td>
                    <td className="px-3 py-1.5">
                      <ClickName
                        value={`${row.origin} - ${row.destination}`}
                        display={row.destination}
                        onClick={onLaneClick}
                      />
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.revenue)}</td>
                    <td className="px-3 py-1.5 text-right text-[#DC2626]">{fmtUsd(row.profit)}</td>
                    <td className="px-3 py-1.5 text-right text-[#DC2626]">{fmtPct(row.margin_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(row.conc_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

// Shared losses combo — always-visible value labels (Bruno 2026-06-03), same
// LabelList pattern as Attrition WoW's Losses tab. Recharts v3: keep the
// formatter callbacks un-annotated and Number() at the call site.
function LossesChart({
  data,
  fmtBucket,
}: {
  data: { bucket: string; loads: number; profit: number }[]
  fmtBucket: (s: string) => string
}) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={data} margin={{ top: 14, right: 16, bottom: 16, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
        <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
        <YAxis yAxisId="left" tick={{ fontSize: 10 }} tickFormatter={(v) => fmtKAxis(Number(v))} />
        <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} />
        <Tooltip
          labelFormatter={(v) => fmtBucket(String(v))}
          formatter={(v, name) =>
            name === "$ Profit (negative)" ? fmtUsd(Number(v)) : fmtCount(Number(v))
          }
        />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        <Bar yAxisId="left" dataKey="profit" name="$ Profit (negative)" fill="#DC2626">
          <LabelList
            dataKey="profit"
            position="bottom"
            fill="#991B1B"
            fontSize={9}
            formatter={(v) => fmtKAxis(Number(v))}
          />
        </Bar>
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="loads"
          name="# Loads"
          stroke="#1F4F99"
          strokeWidth={2}
          dot={{ r: 3 }}
        >
          <LabelList dataKey="loads" position="top" fill="#1F4F99" fontSize={9} />
        </Line>
      </ComposedChart>
    </ResponsiveContainer>
  )
}

function ClickName({
  value,
  display,
  onClick,
}: {
  value: string
  display?: string
  onClick?: (v: string) => void
}) {
  const text = display ?? value
  if (!onClick) return <>{text}</>
  return (
    <button
      type="button"
      onClick={() => onClick(value)}
      className="text-left hover:text-[#1B3A5C] hover:underline"
      title="Filter by this value"
    >
      {text}
    </button>
  )
}

function Spin() {
  return (
    <div className="flex h-40 items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
    </div>
  )
}

function ChartCard({
  title,
  subtitle,
  children,
  loading,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
  loading?: boolean
}) {
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <div className="mb-2">
        <div className="text-sm font-semibold text-[#111827]">{title}</div>
        {subtitle && <div className="text-[10px] text-[#6B7280]">{subtitle}</div>}
      </div>
      {loading ? <Spin /> : children}
    </div>
  )
}
