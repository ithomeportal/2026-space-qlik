"use client"

import { Loader2 } from "lucide-react"
import { useBonusHistory, type BonusHistoryRow } from "@/lib/bonus-api"
import { BRAND, COLORS, usd0, pct } from "../format"
import { ErrorBanner } from "../ErrorBanner"

// Bruno 2026-05-28: monthly history — one row per team per month, frozen at the
// cutoff (6th of the next month 23:59 CST). The still-open current month shows
// live, tagged "in progress".
type Row = {
  teamName: string
  profitUsd: number
  totalBonusUsd: number
  pctBonus: number | null
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th className={`px-4 py-2 text-[11px] font-semibold uppercase tracking-wider ${right ? "text-right" : "text-left"}`}>
      {children}
    </th>
  )
}

function MonthBlock({
  label,
  rows,
  open,
}: {
  label: string
  rows: Row[]
  open?: boolean
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-[#EDE9FE] bg-white shadow-sm">
      <div className="flex items-center justify-between px-4 py-2.5" style={{ background: COLORS.cardBg }}>
        <span className="text-sm font-bold" style={{ color: BRAND }}>
          {label}
        </span>
        {open && (
          <span className="rounded-full bg-[#FEF3C7] px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[#92400E]">
            In progress
          </span>
        )}
      </div>
      <table className="w-full text-sm">
        <thead className="border-b border-[#EDE9FE] text-[#6B7280]">
          <tr>
            <Th>Team</Th>
            <Th>Month - Year</Th>
            <Th right>Profit</Th>
            <Th right>Total Bonus</Th>
            <Th right>% Bonus</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-[#F3F4F6]">
              <td className="px-4 py-2 font-medium text-[#1F2937]">{r.teamName}</td>
              <td className="px-4 py-2 text-[#6B7280]">{label}</td>
              <td className="px-4 py-2 text-right font-mono text-[#1F2937]">{usd0(r.profitUsd)}</td>
              <td className="px-4 py-2 text-right font-mono text-[#1F2937]">{usd0(r.totalBonusUsd)}</td>
              <td className="px-4 py-2 text-right font-mono text-[#1F2937]">{pct(r.pctBonus, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function HistoryTab() {
  const { data, isLoading, isError } = useBonusHistory()
  const d = data?.data

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-[#6B7280]">
        <Loader2 className="mr-2 h-6 w-6 animate-spin" /> Loading history…
      </div>
    )
  }
  if (isError) return <ErrorBanner />

  // Group snapshots by period (newest first — the API already sorts).
  const byPeriod = new Map<string, { label: string; rows: BonusHistoryRow[] }>()
  for (const s of d?.snapshots ?? []) {
    const entry = byPeriod.get(s.periodKey) ?? { label: s.label ?? s.periodKey, rows: [] }
    entry.rows.push(s)
    byPeriod.set(s.periodKey, entry)
  }

  const hasAny = (d?.current?.rows.length ?? 0) > 0 || byPeriod.size > 0

  return (
    <div className="space-y-4">
      <p className="text-xs text-[#6B7280]">
        Monthly bonus history. Each month is frozen at its cutoff — the 6th of the
        following month at 11:59 PM. The current month updates live until then.
      </p>

      {d?.current && d.current.rows.length > 0 && (
        <MonthBlock label={d.current.label} rows={d.current.rows} open />
      )}

      {Array.from(byPeriod.values()).map((g) => (
        <MonthBlock key={g.label} label={g.label} rows={g.rows} />
      ))}

      {!hasAny && (
        <div className="rounded-2xl border border-[#EDE9FE] bg-white py-16 text-center text-sm text-[#9CA3AF]">
          No finalized months yet. History is created automatically after each
          month&apos;s cutoff.
        </div>
      )}
    </div>
  )
}
