"use client"

import { useEffect } from "react"
import { Loader2, X, TrendingDown } from "lucide-react"
import { useLossesLaneTrend } from "@/lib/losses-lanes-api"

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

interface Props {
  lane: string
  teams: string[] | undefined
  customer: string | undefined
  onClose: () => void
}

export function LaneTrendModal({ lane, teams, customer, onClose }: Props) {
  const { data, isLoading, error } = useLossesLaneTrend(lane, teams, customer, 60)
  const rows = data?.data ?? []

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  const totalLoads = rows.reduce((s, r) => s + r.total_loads, 0)
  const totalLossLoads = rows.reduce((s, r) => s + r.loss_loads, 0)
  const totalRevenue = rows.reduce((s, r) => s + r.total_revenue, 0)
  const totalProfit = rows.reduce((s, r) => s + r.total_profit, 0)
  const lossRevenue = rows.reduce((s, r) => s + r.loss_revenue, 0)
  const lossProfit = rows.reduce((s, r) => s + r.loss_profit, 0)

  const maxAbs = Math.max(
    1,
    ...rows.map((r) =>
      Math.max(r.total_revenue, Math.abs(r.total_profit), Math.abs(r.loss_profit)),
    ),
  )

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#E5E7EB] bg-[#FEE2E2] px-4 py-3">
          <div className="flex items-center gap-2">
            <TrendingDown className="h-4 w-4 text-[#DC2626]" />
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-[#991B1B]">
                Lane Trend — last 60 days
              </div>
              <div className="text-sm font-semibold text-[#111827]">{lane}</div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-[#6B7280] hover:bg-white hover:text-[#111827]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid grid-cols-3 gap-2 border-b border-[#E5E7EB] bg-[#F9FAFB] p-3 text-xs md:grid-cols-6">
          <StatCell label="Total loads" value={fmtCount(totalLoads)} />
          <StatCell label="Losing loads" value={fmtCount(totalLossLoads)} tone="red" />
          <StatCell label="Total revenue" value={fmtUsd(totalRevenue)} />
          <StatCell label="Total profit" value={fmtUsd(totalProfit)} tone={totalProfit < 0 ? "red" : "green"} />
          <StatCell label="Loss revenue" value={fmtUsd(lossRevenue)} />
          <StatCell label="Loss profit" value={fmtUsd(lossProfit)} tone="red" />
        </div>

        <div className="flex-1 overflow-auto p-4">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
            </div>
          )}
          {!!error && !isLoading && (
            <div className="rounded-lg border border-[#FCA5A5] bg-[#FEE2E2] px-3 py-2 text-xs text-[#991B1B]">
              Lane trend query failed: {(error as Error).message}
            </div>
          )}
          {!isLoading && rows.length === 0 && !error && (
            <div className="py-12 text-center text-xs text-[#6B7280]">
              No loads for this lane in the last 60 days.
            </div>
          )}
          <div className="space-y-1">
            {rows.map((r) => {
              const revW = (r.total_revenue / maxAbs) * 100
              const profW = (Math.abs(r.total_profit) / maxAbs) * 100
              const lossW = (Math.abs(r.loss_profit) / maxAbs) * 100
              return (
                <div
                  key={r.bucket}
                  className="grid grid-cols-[80px_1fr_140px] items-center gap-2 border-b border-[#F3F4F6] py-1 text-xs"
                >
                  <span className="font-medium text-[#111827]">{r.bucket}</span>
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-1">
                      <span className="w-10 text-[10px] text-[#1B3A5C]">Rev</span>
                      <div className="h-1.5 flex-1 rounded bg-[#F3F4F6]">
                        <div
                          className="h-1.5 rounded bg-[#1B3A5C]"
                          style={{ width: `${revW}%` }}
                        />
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="w-10 text-[10px] text-[#B45309]">Profit</span>
                      <div className="h-1.5 flex-1 rounded bg-[#F3F4F6]">
                        <div
                          className={`h-1.5 rounded ${r.total_profit < 0 ? "bg-[#B91C1C]" : "bg-[#047857]"}`}
                          style={{ width: `${profW}%` }}
                        />
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="w-10 text-[10px] text-[#991B1B]">Loss</span>
                      <div className="h-1.5 flex-1 rounded bg-[#F3F4F6]">
                        <div
                          className="h-1.5 rounded bg-[#991B1B]"
                          style={{ width: `${lossW}%` }}
                        />
                      </div>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-1 text-right text-[10px] text-[#6B7280]">
                    <span>{fmtCount(r.total_loads)}L</span>
                    <span className={r.total_profit < 0 ? "text-[#B91C1C]" : "text-[#047857]"}>
                      {fmtUsd(r.total_profit)}
                    </span>
                    <span className="text-[#991B1B]">{fmtCount(r.loss_loads)}x</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

function StatCell({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: "red" | "green"
}) {
  const color =
    tone === "red" ? "text-[#B91C1C]" : tone === "green" ? "text-[#047857]" : "text-[#111827]"
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className={`text-sm font-semibold ${color}`}>{value}</div>
    </div>
  )
}
