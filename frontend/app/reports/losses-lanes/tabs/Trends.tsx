"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import {
  useLossesByDay,
  useLossesByMonth,
  useLossesByWeek,
  type LossesFilters,
  type LossesTrendPoint,
} from "@/lib/losses-lanes-api"
import { LossesErrorBanner } from "../ErrorBanner"

const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const COUNT = new Intl.NumberFormat("en-US")

const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))
const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT.format(Number(v))

type Granularity = "day" | "week" | "month"

interface Props {
  filters: LossesFilters
}

export function Trends({ filters }: Props) {
  const [gran, setGran] = useState<Granularity>("day")
  const teamsForSticky = filters.teams
  const customerForSticky = filters.customer

  const dayRes = useLossesByDay(filters)
  const weekRes = useLossesByWeek(teamsForSticky, customerForSticky)
  const monthRes = useLossesByMonth(teamsForSticky, customerForSticky)

  const active = gran === "day" ? dayRes : gran === "week" ? weekRes : monthRes
  const rows: LossesTrendPoint[] = active.data?.data ?? []

  const stickyNote =
    gran === "day"
      ? "Respects the selected date range."
      : gran === "week"
        ? "Sticky: last 8 weeks (ignores date filter — matches Bruno's Qlik)."
        : "Sticky: last 6 months (ignores date filter — matches Bruno's Qlik)."

  const maxAbs = Math.max(
    1,
    ...rows.map((r) => Math.max(r.revenue, Math.abs(r.profit))),
  )
  const maxLoads = Math.max(1, ...rows.map((r) => r.loads))

  return (
    <div className="space-y-3">
      <LossesErrorBanner
        errors={[dayRes.error, weekRes.error, monthRes.error]}
        label="Trends"
      />
      <div className="flex items-center justify-between">
        <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
          {(["day", "week", "month"] as Granularity[]).map((g) => (
            <button
              key={g}
              onClick={() => setGran(g)}
              className={`px-3 py-1.5 capitalize ${
                gran === g
                  ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                  : "text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              by {g}
            </button>
          ))}
        </div>
        <div className="text-xs text-[#6B7280]">{stickyNote}</div>
        {active.isLoading && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
      </div>

      <div className="rounded-lg border border-[#E5E7EB] bg-white p-4 shadow-sm">
        {rows.length === 0 && !active.isLoading && (
          <div className="py-8 text-center text-xs text-[#6B7280]">
            No losing loads in this window.
          </div>
        )}
        <div className="space-y-2">
          {rows.map((r) => {
            const revW = (r.revenue / maxAbs) * 100
            const profitW = (Math.abs(r.profit) / maxAbs) * 100
            const loadsW = (r.loads / maxLoads) * 100
            return (
              <div key={r.bucket} className="border-b border-[#F3F4F6] pb-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium text-[#111827]">{r.bucket}</span>
                  <div className="flex items-center gap-4">
                    <span className="text-[#1B3A5C]">Rev {fmtUsd(r.revenue)}</span>
                    <span className="text-[#B91C1C]">Profit {fmtUsd(r.profit)}</span>
                    <span className="text-[#B45309]">{fmtCount(r.loads)} loads</span>
                  </div>
                </div>
                <div className="mt-1 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="w-12 text-[10px] text-[#1B3A5C]">Rev</span>
                    <div className="h-2 flex-1 rounded bg-[#F3F4F6]">
                      <div
                        className="h-2 rounded bg-[#1B3A5C]"
                        style={{ width: `${revW}%` }}
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-12 text-[10px] text-[#B91C1C]">Loss</span>
                    <div className="h-2 flex-1 rounded bg-[#F3F4F6]">
                      <div
                        className="h-2 rounded bg-[#B91C1C]"
                        style={{ width: `${profitW}%` }}
                      />
                    </div>
                  </div>
                  {gran === "day" && (
                    <div className="flex items-center gap-2">
                      <span className="w-12 text-[10px] text-[#B45309]">Loads</span>
                      <div className="relative h-2 flex-1 rounded bg-[#F3F4F6]">
                        <div
                          className="absolute top-1/2 h-3 w-3 -translate-y-1/2 rounded-full bg-[#B45309]"
                          style={{ left: `calc(${loadsW}% - 6px)` }}
                        />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
