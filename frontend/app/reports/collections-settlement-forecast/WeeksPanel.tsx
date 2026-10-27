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
  fmtDay,
  fmtUsd,
  fmtUsdCompact,
  signTone,
  useWeeks,
  weekLabel,
  type WeekRow,
} from "@/lib/collections-settlement-forecast-api"
import { ErrorBox } from "./ThisWeekPanel"

function Chart({ rows }: { rows: WeekRow[] }) {
  const data = rows.map((r) => ({
    label: fmtDay(r.week_end),
    in: r.cash_in,
    out: r.cash_out === null ? null : -r.cash_out,
    cumulative: r.cumulative,
  }))
  return (
    <div className="h-72 rounded-xl border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
          <YAxis tickFormatter={(v: number) => fmtUsdCompact(v)} tick={{ fontSize: 11 }} width={70} />
          <Tooltip formatter={(v) => fmtUsd(typeof v === "number" ? Math.abs(v) : null)} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="in" name="Cash in" fill="#10B981" />
          <Bar dataKey="out" name="Cash out" fill="#F87171" />
          <Line dataKey="cumulative" name="Cumulative net" stroke="#1B3A5C" strokeWidth={2} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

const BASIS_TIP: Record<string, string> = {
  "run-rate": "After McLeod's last scheduled pay run — Bruce's 3-week average",
  scheduled: "McLeod's Friday settlement pay run",
}

function Basis({ v }: { v: string | null }) {
  if (!v) return <span>—</span>
  const tone = v === "run-rate" ? "bg-[#FEF3C7] text-[#92400E]" : "bg-[#F3F4F6] text-[#4B5563]"
  return <span className={`rounded px-1.5 py-0.5 text-[10px] ${tone}`} title={BASIS_TIP[v]}>{v}</span>
}

export function WeeksPanel() {
  const { data, isLoading, error } = useWeeks()
  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
      </div>
    )
  }
  const rows = data.data
  const m = data.meta
  return (
    <div className="space-y-4">
      <Chart rows={rows} />
      <div className="overflow-x-auto rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
        <table className="w-full text-xs">
          <thead className="bg-[#F9FAFB] text-[#6B7280]">
            <tr>
              <th className="px-3 py-1.5 text-left">Week (Sat – Fri)</th>
              <th className="px-3 py-1.5 text-right" title="Bruce's expected collections">Cash in</th>
              <th className="px-3 py-1.5 text-right" title="Part of cash in from customers' 3-week run-rate (loads not shipped yet)">of which run-rate</th>
              <th className="px-3 py-1.5 text-right" title="Open AR due by invoice terms that week; this week = committed basis">Due by terms</th>
              <th className="px-3 py-1.5 text-right">Settlements</th>
              <th className="px-3 py-1.5 text-left">Basis</th>
              <th className="px-3 py-1.5 text-right">Vendor AP</th>
              <th className="px-3 py-1.5 text-right">Cash out</th>
              <th className="px-3 py-1.5 text-right">Net</th>
              <th className="px-3 py-1.5 text-right">Cumulative</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.week_start} className={`border-t border-[#F3F4F6] ${r.week_offset === 0 ? "bg-[#EFF6FF]" : ""}`}>
                <td className="px-3 py-1.5">
                  {weekLabel(r.week_start, r.week_end)}
                  {r.week_offset === 0 && <span className="ml-1 text-[10px] text-[#1D4ED8]">this week</span>}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.cash_in)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-[#92400E]">{r.in_run_rate ? fmtUsd(r.in_run_rate) : ""}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-[#6B7280]">{fmtUsd(r.in_due_terms)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.settlements)}</td>
                <td className="px-3 py-1.5"><Basis v={r.out_basis} /></td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.ap)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.cash_out)}</td>
                <td className={`px-3 py-1.5 text-right font-semibold tabular-nums ${signTone(r.net)}`}>{fmtUsd(r.net)}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${signTone(r.cumulative)}`}>{fmtUsd(r.cumulative)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-[#6B7280]">
        Cash in is Bruce&apos;s EXPECTED basis: shipped revenue on bill date + each customer&apos;s average days to
        pay; weeks whose loads have not shipped take the customer&apos;s 3-week run-rate. This week&apos;s committed
        basis is {fmtUsd(m.this_week_committed_in)}; typical collected week {fmtUsd(m.typical_week)}. Settlements
        McLeod schedules beyond its weekly buckets ({fmtUsd(m.settlements_unplaced)}) are not placed in a week.
        Payroll, loans and other recurring obligations are not included.
      </p>
    </div>
  )
}
