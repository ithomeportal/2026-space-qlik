"use client"

import { Loader2 } from "lucide-react"
import { fmtDay, fmtUsd, signTone, useAccuracy, weekLabel } from "@/lib/collections-settlement-forecast-api"
import { ErrorBox } from "./ThisWeekPanel"

export function AccuracyPanel() {
  const { data, isLoading, error } = useAccuracy()
  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
      </div>
    )
  }
  const rows = [...data.data].reverse()
  const first = data.meta.first_snapshot
  return (
    <div className="space-y-3">
      <p className="text-xs text-[#6B7280]">
        The forecast is stored every day at 06:30 CST; a week is compared with the forecast taken on its first day.
        {first ? ` History starts ${fmtDay(first)}.` : " No forecast stored yet — history starts with the first daily run."}
      </p>
      <div className="overflow-x-auto rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
        <table className="w-full text-xs">
          <thead className="bg-[#F9FAFB] text-[#6B7280]">
            <tr>
              <th className="px-3 py-1.5 text-left">Week (Sat – Fri)</th>
              <th className="px-3 py-1.5 text-right" title="Expected basis, taken on the week's first day">Forecast in</th>
              <th className="px-3 py-1.5 text-right">Committed in</th>
              <th className="px-3 py-1.5 text-right" title="Taken the week before">Forecast a week ahead</th>
              <th className="px-3 py-1.5 text-right">Collected</th>
              <th className="px-3 py-1.5 text-right">Variance in</th>
              <th className="px-3 py-1.5 text-right">Forecast settlements</th>
              <th className="px-3 py-1.5 text-right" title="The week's final pay run as last scheduled">Settled</th>
              <th className="px-3 py-1.5 text-right">Variance out</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.week_start} className="border-t border-[#F3F4F6]">
                <td className="px-3 py-1.5">
                  {weekLabel(r.week_start, r.week_end)}
                  {!r.complete && <span className="ml-1 text-[10px] text-[#1D4ED8]">in progress</span>}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.forecast_in)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.forecast_in_committed)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.forecast_in_prior_week)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.actual_in)}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${signTone(r.variance_in)}`}>{fmtUsd(r.variance_in)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.forecast_settlements)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.actual_settlements)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.variance_settlements)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-[#6B7280]">
        Collected = cash receipts with a GL date in the week. Variance = actual − forecast.
      </p>
    </div>
  )
}
