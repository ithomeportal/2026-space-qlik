"use client"

import { useState } from "react"
import { Loader2, ExternalLink } from "lucide-react"
import { useLossesTopLanesCombo, type LossesFilters } from "@/lib/losses-lanes-api"
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

interface Props {
  filters: LossesFilters
  onDrillLane: (lane: string) => void
}

export function TopCombo({ filters, onDrillLane }: Props) {
  const [limit, setLimit] = useState(10)
  const { data, isLoading, error } = useLossesTopLanesCombo(filters, limit)
  const rows = data?.data ?? []

  // Normalize bar heights: scale by max revenue so profit bars read relatively.
  const maxRevenue = Math.max(1, ...rows.map((r) => r.revenue))
  const maxLoss = Math.max(1, ...rows.map((r) => Math.abs(r.profit)))
  const maxLoads = Math.max(1, ...rows.map((r) => r.loads))

  return (
    <div className="space-y-3">
      <LossesErrorBanner errors={[error]} label="Top Combo" />
      <div className="flex items-center justify-between">
        <div className="text-xs text-[#6B7280]">
          Top {limit} losing lanes · revenue + negative profit, with load count
        </div>
        <div className="flex items-center gap-2 text-xs">
          <label className="text-[#6B7280]">Top</label>
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="rounded border border-[#E5E7EB] bg-white px-2 py-1"
          >
            {[10, 20, 30, 50].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          {isLoading && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
        </div>
      </div>

      <div className="rounded-lg border border-[#E5E7EB] bg-white p-4 shadow-sm">
        {rows.length === 0 && !isLoading && (
          <div className="py-8 text-center text-xs text-[#6B7280]">
            No losing lanes in this window.
          </div>
        )}
        <div className="space-y-2">
          {rows.map((r, i) => {
            const revW = (r.revenue / maxRevenue) * 100
            const lossW = (Math.abs(r.profit) / maxLoss) * 100
            const loadDot = (r.loads / maxLoads) * 100
            return (
              <div key={`${r.lane ?? ""}-${i}`} className="border-b border-[#F3F4F6] pb-2">
                <div className="flex items-center justify-between text-xs">
                  <button
                    onClick={() => r.lane && onDrillLane(r.lane)}
                    className="inline-flex items-center gap-1 text-left font-medium text-[#111827] hover:text-[#1B3A5C]"
                  >
                    {r.lane ?? "—"}
                    {r.lane && <ExternalLink className="h-3 w-3 opacity-60" />}
                  </button>
                  <div className="flex items-center gap-4">
                    <span className="text-[#1B3A5C]">Rev {fmtUsd(r.revenue)}</span>
                    <span className="text-[#B91C1C]">Profit {fmtUsd(r.profit)}</span>
                    <span className="text-[#B45309]">
                      {fmtCount(r.loads)} loads
                    </span>
                  </div>
                </div>
                <div className="mt-1 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="w-10 text-[10px] text-[#1B3A5C]">Rev</span>
                    <div className="h-2 flex-1 rounded bg-[#F3F4F6]">
                      <div
                        className="h-2 rounded bg-[#1B3A5C]"
                        style={{ width: `${revW}%` }}
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-10 text-[10px] text-[#B91C1C]">Loss</span>
                    <div className="h-2 flex-1 rounded bg-[#F3F4F6]">
                      <div
                        className="h-2 rounded bg-[#B91C1C]"
                        style={{ width: `${lossW}%` }}
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-10 text-[10px] text-[#B45309]">Loads</span>
                    <div className="relative h-2 flex-1 rounded bg-[#F3F4F6]">
                      <div
                        className="absolute top-1/2 h-3 w-3 -translate-y-1/2 rounded-full bg-[#B45309]"
                        style={{ left: `calc(${loadDot}% - 6px)` }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
