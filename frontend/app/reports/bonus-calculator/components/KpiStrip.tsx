import { HandCoins, TrendingUp, Calculator, Database } from "lucide-react"
import type { BonusReport } from "@/lib/bonus-api"
import { BRAND, COLORS, usd0, pct } from "../format"

function Kpi({
  label,
  value,
  sub,
  Icon,
  accent,
}: {
  label: string
  value: string
  sub: string
  Icon: React.ComponentType<{ className?: string }>
  accent?: string
}) {
  return (
    <div className="flex items-center justify-between rounded-2xl border border-[#EDE9FE] bg-white px-5 py-4 shadow-sm">
      <div>
        <p className="text-[10px] font-bold uppercase tracking-[0.12em]" style={{ color: COLORS.cardTitle }}>
          {label}
        </p>
        <p className="mt-1 text-2xl font-bold" style={{ color: accent || "#111827" }}>
          {value}
        </p>
        <p className="text-xs text-[#6B7280]">{sub}</p>
      </div>
      <div className="flex h-11 w-11 items-center justify-center rounded-xl" style={{ background: COLORS.cardBg }}>
        <Icon className="h-5 w-5" />
      </div>
    </div>
  )
}

export function KpiStrip({ report }: { report: BonusReport }) {
  const connected = report.dataSource.status.toLowerCase() === "connected"
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Kpi
        label="Total Bonus"
        value={usd0(report.totals.grandBonusUsd)}
        sub="Teams and night/weekend"
        Icon={HandCoins}
      />
      <Kpi
        label="Total Profit"
        value={usd0(report.totals.totalProfit)}
        sub="Operations teams from report"
        Icon={TrendingUp}
      />
      <Kpi
        label="Bonus / Profit"
        value={pct(report.totals.bonusAsPctOfProfit)}
        sub="Control metric for HR review"
        Icon={Calculator}
      />
      <Kpi
        label="McLeod Status"
        value={report.dataSource.status}
        sub={report.dataSource.lastSyncLabel}
        Icon={Database}
        accent={connected ? BRAND : "#6B7280"}
      />
    </div>
  )
}
