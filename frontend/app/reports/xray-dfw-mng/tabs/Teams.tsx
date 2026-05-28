"use client"

import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useXrayDfwTeamsBreakdown,
  type XrayDfwFilters,
  type XrayDfwTeamBucket,
  type XrayDfwTeamBreakdownRow,
} from "@/lib/xray-dfw-api"
import { SortableTh, type SortDir, type SortState } from "@/components/SortableTable"
import { XrayDfwErrorBanner } from "../ErrorBanner"

interface Props {
  filters: XrayDfwFilters
}

type Metric = "loads" | "profit" | "margin"

const COLS: { key: keyof Omit<XrayDfwTeamBreakdownRow, "team">; label: string }[] = [
  { key: "tm", label: "TM" },
  { key: "tw", label: "TW" },
  { key: "l1w", label: "LW" },
  { key: "l2w", label: "L2W" },
  { key: "l3w", label: "L3W" },
  { key: "l4w", label: "L4W" },
  { key: "l5w", label: "L5W" },
  { key: "avg_l5w", label: "AVG L5W" },
  { key: "avg_l5w_minus_lw", label: "AVG L5W − LW" },
]

export function Teams({ filters }: Props) {
  const { data, isLoading, error } = useXrayDfwTeamsBreakdown({
    customers: filters.customers,
    lanes: filters.lanes,
    view: filters.view,
  })
  const breakdown = data?.data

  return (
    <div className="space-y-6">
      <XrayDfwErrorBanner label="Teams" errors={[error]} />
      <TeamTable title="Loads by Teams" tone="red" metric="loads" data={breakdown} loading={isLoading} />
      <TeamTable title="Profit by Teams" tone="yellow" metric="profit" data={breakdown} loading={isLoading} />
      <TeamTable title="Margin by Teams" tone="purple" metric="margin" data={breakdown} loading={isLoading} />
    </div>
  )
}

function TeamTable({
  title,
  tone,
  metric,
  data,
  loading,
}: {
  title: string
  tone: "red" | "yellow" | "purple"
  metric: Metric
  data:
    | { teams: XrayDfwTeamBreakdownRow[]; totals: Omit<XrayDfwTeamBreakdownRow, "team"> }
    | undefined
  loading?: boolean
}) {
  const headerBg =
    tone === "red" ? "bg-[#FEE2E2]" : tone === "yellow" ? "bg-[#FEF3C7]" : "bg-[#EDE9FE]"

  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  const toggleSort = (key: string) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    else {
      setSortKey(key)
      setSortDir("desc")
    }
  }
  const sortState: SortState = { sortKey, sortDir, toggleSort }

  const metricVal = (b: XrayDfwTeamBucket | undefined) => {
    if (!b) return 0
    if (metric === "loads") return b.loads
    if (metric === "profit") return b.profit
    return b.margin_pct
  }

  const render = (b: XrayDfwTeamBucket) => {
    if (metric === "loads") return fmtCount(b.loads)
    if (metric === "profit") return fmtUsd(b.profit)
    return fmtPct(b.margin_pct)
  }

  const sortedTeams = useMemo(() => {
    if (!data) return []
    if (!sortKey) return data.teams
    const copy = [...data.teams]
    copy.sort((a, b) => {
      let c: number
      if (sortKey === "team") {
        c = String(a.team ?? "").localeCompare(String(b.team ?? ""), undefined, { numeric: true })
      } else {
        const av = metricVal(a[sortKey as keyof Omit<XrayDfwTeamBreakdownRow, "team">] as XrayDfwTeamBucket)
        const bv = metricVal(b[sortKey as keyof Omit<XrayDfwTeamBreakdownRow, "team">] as XrayDfwTeamBucket)
        c = av - bv
      }
      return sortDir === "asc" ? c : -c
    })
    return copy
  }, [data, sortKey, sortDir, metric])

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className={`${headerBg} px-3 py-2 text-sm font-semibold text-[#111827]`}>{title}</div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : !data ? null : (
        <div className="overflow-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className={`${headerBg} text-[#6B7280]`}>
              <tr>
                <SortableTh label="Team" columnKey="team" state={sortState} />
                {COLS.map((c) => (
                  <SortableTh
                    key={c.key}
                    label={c.label}
                    columnKey={c.key}
                    state={sortState}
                    align="right"
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              <tr className="border-t border-[#E5E7EB] bg-[#F9FAFB] font-semibold">
                <td className="px-3 py-1.5">Totals</td>
                {COLS.map((c) => (
                  <td key={c.key} className="px-2 py-1.5 text-right">
                    {render(data.totals[c.key])}
                  </td>
                ))}
              </tr>
              {sortedTeams.map((r) => (
                <tr key={r.team} className="border-t border-[#F3F4F6] hover:bg-[#F9FAFB]">
                  <td className="px-3 py-1.5">{r.team}</td>
                  {COLS.map((c) => {
                    const bucket = (r as XrayDfwTeamBreakdownRow)[c.key] as XrayDfwTeamBucket
                    return (
                      <td key={c.key} className="px-2 py-1.5 text-right">
                        {render(bucket)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
