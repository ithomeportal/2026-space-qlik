"use client"

import { useEffect, useMemo, useState } from "react"
import { Loader2 } from "lucide-react"
import {
  Brush,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  fmtBucket,
  fmtCount,
  useOppService,
  type LoadType,
  type OppFilters,
  type OppGrain,
} from "@/lib/ops-portal-overview-api"

interface Props {
  filters: OppFilters
  loadType: LoadType
}

const GRAINS: { k: OppGrain; label: string; defaultVisible: number }[] = [
  { k: "day", label: "Day", defaultVisible: 30 },
  { k: "week", label: "Week", defaultVisible: 13 },
  { k: "month", label: "Month", defaultVisible: 13 },
]

// Bruno R4 (2026-05-27): second "KPI MANAGEMENT" section — "Service".
// OTP% / OTD% over the same Day/Week/Month grain. Production data.
export function ServiceChart({ filters, loadType }: Props) {
  const cf = { team: filters.team, customer: filters.customer, loadType }
  const [grain, setGrain] = useState<OppGrain>("month")
  const { data: res, isLoading, error } = useOppService(cf, grain)

  const buckets = useMemo(() => res?.data?.buckets ?? [], [res])
  const chartData = useMemo(
    () => buckets.map((b) => ({ ...b, label: fmtBucket(b.bucket_start, grain) })),
    [buckets, grain],
  )

  const defaultVisible = GRAINS.find((g) => g.k === grain)?.defaultVisible ?? 13
  const [brush, setBrush] = useState<{ start: number; end: number }>({ start: 0, end: 0 })
  useEffect(() => {
    if (!chartData.length) return
    const end = chartData.length - 1
    const start = Math.max(0, end - defaultVisible + 1)
    setBrush({ start, end })
  }, [grain, chartData.length, defaultVisible])

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
          KPI Management
        </span>
        <span className="rounded-md bg-[#0E7490] px-2 py-0.5 text-xs font-semibold uppercase text-white">
          Service
        </span>
        <div className="flex rounded-lg border border-[#E5E7EB] bg-white text-xs">
          {GRAINS.map((g) => (
            <button
              key={g.k}
              onClick={() => setGrain(g.k)}
              className={`px-3 py-1 ${
                grain === g.k
                  ? "bg-[#1B3A5C] font-semibold text-white"
                  : "text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {g.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3 text-[11px]">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-4 rounded-sm bg-[#16A34A]" /> OTP %
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-4 rounded-sm bg-[#2563EB]" /> OTD %
          </span>
        </div>
      </div>

      <div className="px-3 py-3">
        {isLoading ? (
          <div className="flex h-[260px] items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : error ? (
          <div className="flex h-[260px] items-center justify-center text-sm text-[#DC2626]">
            Failed to load Service
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={chartData} margin={{ top: 16, right: 24, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis
                tick={{ fontSize: 10 }}
                domain={[0, 100]}
                tickFormatter={(v) => `${Number(v).toFixed(0)}%`}
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload || !payload.length) return null
                  const row = payload[0].payload as {
                    label?: string; otp_pct: number; otd_pct: number; volume: number
                  }
                  return (
                    <div className="rounded-md border border-[#E5E7EB] bg-white px-3 py-2 text-xs shadow-md">
                      <div className="mb-1 font-semibold text-[#111827]">{row.label}</div>
                      <div className="flex items-center justify-between gap-4">
                        <span className="flex items-center gap-1.5">
                          <span className="inline-block h-2 w-2 rounded-full bg-[#16A34A]" /> OTP %
                        </span>
                        <span className="font-medium tabular-nums">{row.otp_pct.toFixed(2)}%</span>
                      </div>
                      <div className="flex items-center justify-between gap-4">
                        <span className="flex items-center gap-1.5">
                          <span className="inline-block h-2 w-2 rounded-full bg-[#2563EB]" /> OTD %
                        </span>
                        <span className="font-medium tabular-nums">{row.otd_pct.toFixed(2)}%</span>
                      </div>
                      <div className="mt-1 border-t border-[#F3F4F6] pt-1 text-[10px] text-[#6B7280]">
                        Volume {fmtCount(row.volume)}
                      </div>
                    </div>
                  )
                }}
              />
              <Line
                type="monotone"
                dataKey="otp_pct"
                name="OTP %"
                stroke="#16A34A"
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="otd_pct"
                name="OTD %"
                stroke="#2563EB"
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
              <Brush
                dataKey="label"
                height={20}
                stroke="#94A3B8"
                travellerWidth={8}
                startIndex={brush.start}
                endIndex={brush.end}
                onChange={(r) => {
                  if (r && typeof r.startIndex === "number" && typeof r.endIndex === "number") {
                    setBrush({ start: r.startIndex, end: r.endIndex })
                  }
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  )
}
