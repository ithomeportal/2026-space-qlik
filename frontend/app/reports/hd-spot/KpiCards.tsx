"use client"

import { Loader2 } from "lucide-react"
import {
  useHdSpotSummary,
  fmtPct,
  fmtUsd,
  fmtVol,
  type HdSpotFilters,
} from "@/lib/hd-spot-api"

interface CardProps {
  label: string
  value: string
  sub?: string
  title?: string
  tone?: "default" | "warn"
}

function Card({ label, value, sub, title, tone = "default" }: CardProps) {
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-3 shadow-sm" title={title}>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div
        className={`mt-1 text-xl font-semibold ${
          tone === "warn" ? "text-[#B45309]" : "text-[#1B3A5C]"
        }`}
      >
        {value}
      </div>
      {/* Always render the slot so the cards keep a uniform height. */}
      <div className="mt-0.5 h-4 text-[10px] text-[#9CA3AF]">{sub ?? ""}</div>
    </div>
  )
}

export function KpiCards({ filters }: { filters: HdSpotFilters }) {
  const { data, isLoading, error } = useHdSpotSummary(filters)
  const k = data?.data

  if (error) {
    return (
      <div className="rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-xs text-[#991B1B]">
        Could not load KPIs: {error instanceof Error ? error.message : "unknown error"}
      </div>
    )
  }
  if (isLoading && !k) {
    return (
      <div className="flex h-24 items-center justify-center rounded-xl border border-[#E5E7EB] bg-white">
        <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
      </div>
    )
  }

  // The money half fails soft — the funnel still renders and these read "—".
  const moneyDown = k && k.money_ok === false

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Card label="Offered" value={fmtVol(k?.offered)} sub="Σ volume" />
        <Card label="Quoted" value={fmtVol(k?.quoted)} sub="volume w/ a buy rate" />
        <Card
          label="Participation"
          value={fmtPct(k?.participation)}
          sub="quoted ÷ offered"
        />
        <Card label="Awarded" value={fmtVol(k?.awarded)} sub="volume WON" />
        <Card
          label="Conversion"
          value={fmtPct(k?.conversion)}
          sub="awarded ÷ quoted"
          title="Awarded counts award_status = WON only. ACCEPT means a price was submitted to Home Depot and the outcome is still pending — those orders do not become shipments."
        />
        <Card
          label="Revenue Covered"
          value={moneyDown ? "—" : fmtUsd(k?.revenue_covered)}
          sub="in progress + delivered"
        />
        <Card
          label="Profit Covered"
          value={moneyDown ? "—" : fmtUsd(k?.profit_covered)}
          sub="Σ margin, covered only"
        />
        <Card
          label="Margin Covered"
          value={moneyDown ? "—" : fmtPct(k?.margin_covered)}
          sub="profit ÷ revenue"
          title="Covered basis on purpose. A blended margin is inflated: cancelled loads keep their revenue but shed carrier pay (~100% margin), and Pending-to-Cover loads have not been paid out yet."
        />
      </div>

      {moneyDown && (
        <div className="rounded-lg border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2 text-[11px] text-[#92400E]">
          The McLeod side is unavailable right now, so revenue, profit and margin
          are blank. The funnel figures above are unaffected.
        </div>
      )}

      {!moneyDown && k && k.match_rate !== null && k.match_rate < 0.85 && (
        <div className="rounded-lg border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2 text-[11px] text-[#92400E]">
          {k.won_orders_matched} of {k.won_orders} awarded orders matched a McLeod
          load ({fmtPct(k.match_rate, 0)}). Money figures cover the matched ones
          only — recently awarded loads take a while to appear in McLeod.
        </div>
      )}
    </div>
  )
}
