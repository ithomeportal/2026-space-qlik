"use client"

import Link from "next/link"
import { ArrowLeft, Loader2, Trophy } from "lucide-react"
import {
  usePodiumTop,
  type PodiumLeaderboards,
} from "@/lib/podium-top-api"
import { fmtCurrency, fmtInt, fmtPct } from "@/lib/podium-dfw-api"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"

export default function DfwPodiumTopPage() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["dfw-podium-top"]]}>
      <DfwPodiumTopContent />
    </RoleGuard>
  )
}

function DfwPodiumTopContent() {
  const q = usePodiumTop()
  const data = q.data?.data
  const lastUpdated = q.dataUpdatedAt ? new Date(q.dataUpdatedAt) : null

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link
          href="/"
          className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <div className="flex items-center gap-2">
          <Trophy className="h-4 w-4 text-[#C2410C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">DFW Podium Top</h1>
          <span className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-xs text-[#92400E]">
            DFW
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          {q.isFetching && (
            <span className="inline-flex items-center gap-1 text-[#6B7280]">
              <Loader2 className="h-3 w-3 animate-spin" />
              Refreshing
            </span>
          )}
          {lastUpdated && (
            <span>
              Last updated{" "}
              {lastUpdated.toLocaleTimeString("en-US", {
                hour: "2-digit",
                minute: "2-digit",
              })}{" "}
              CST
            </span>
          )}
          <span className="text-[#9CA3AF]">·</span>
          <span>Auto-refresh every 15 min</span>
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-4 px-6 py-5">
        {q.error ? (
          <div className="rounded-md border border-[#FCA5A5] bg-[#FEF2F2] px-3 py-2 text-xs text-[#991B1B]">
            Failed to load DFW Podium Top data.
            {q.error instanceof Error ? ` (${q.error.message})` : ""}
          </div>
        ) : null}

        <Podiums data={data} loading={q.isLoading} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Podium leaderboards -- top 3 each
// Totals row = sum of just the displayed (≤3) rows.
// Margin total is recomputed as ΣProfit / ΣRevenue across displayed rows.
// ---------------------------------------------------------------------------
type PodiumColumn = {
  header: string
  align?: "left" | "right"
  value: (row: Record<string, unknown>) => string
  num?: (row: Record<string, unknown>) => number | null
  totalsRole?: "sum" | "marginPct" | "skip"
}

function Podiums({
  data,
  loading,
}: {
  data: PodiumLeaderboards | undefined
  loading: boolean
}) {
  if (loading || !data) {
    return (
      <section className="rounded-lg border border-[#E5E7EB] bg-white p-3">
        <div className="flex items-center gap-2 text-xs text-[#6B7280]">
          <Loader2 className="h-3 w-3 animate-spin" />
          Loading podium leaderboards…
        </div>
      </section>
    )
  }

  const profitCol: PodiumColumn = {
    header: "Profit",
    align: "right",
    value: (r) => fmtCurrency(r.profit as number | null | undefined),
    num: (r) => (typeof r.profit === "number" ? r.profit : null),
    totalsRole: "sum",
  }
  const loadsCol: PodiumColumn = {
    header: "Loads",
    align: "right",
    value: (r) => fmtInt(r.loads as number | null | undefined),
    num: (r) => (typeof r.loads === "number" ? r.loads : null),
    totalsRole: "sum",
  }
  const marginCol: PodiumColumn = {
    header: "Margin %",
    align: "right",
    value: (r) => fmtPct(r.margin_pct as number | null | undefined),
    totalsRole: "marginPct",
  }
  const postedByCol: PodiumColumn = {
    header: "Posted by",
    align: "left",
    value: (r) => (r.posted_by as string) ?? "—",
    totalsRole: "skip",
  }

  return (
    <section className="space-y-3">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <PodiumTable
          title="TOP 3 Bookers by Profit"
          subtitle="This Week"
          rows={data.week_top_profit as unknown as Record<string, unknown>[]}
          accent="#C2410C"
          columns={[postedByCol, profitCol, loadsCol]}
        />
        <PodiumTable
          title="TOP 3 Bookers by Margin"
          subtitle="This Week"
          rows={data.week_top_margin as unknown as Record<string, unknown>[]}
          accent="#1B3A5C"
          columns={[postedByCol, marginCol, loadsCol]}
        />
        <PodiumTable
          title="TOP 3 Bookers by Loads"
          subtitle="This Week"
          rows={data.week_top_loads as unknown as Record<string, unknown>[]}
          accent="#DC2626"
          columns={[postedByCol, loadsCol]}
        />
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <PodiumTable
          title="TOP Bookers by Loads"
          subtitle="Today"
          rows={data.today_top_loads as unknown as Record<string, unknown>[]}
          accent="#DC2626"
          columns={[postedByCol, loadsCol]}
        />
        <PodiumTable
          title="TOP Bookers by Profit"
          subtitle="Today"
          rows={data.today_top_profit as unknown as Record<string, unknown>[]}
          accent="#C2410C"
          columns={[postedByCol, profitCol]}
        />
      </div>
    </section>
  )
}

const MEDALS = ["🥇", "🥈", "🥉"]

function PodiumTable({
  title,
  subtitle,
  rows,
  columns,
  accent,
}: {
  title: string
  subtitle: string
  rows: Record<string, unknown>[]
  columns: PodiumColumn[]
  accent: string
}) {
  // Totals row -- sum of just the displayed rows (top 3 only).
  const totals: Record<number, string> = {}
  columns.forEach((col, idx) => {
    if (col.totalsRole === "sum" && col.num) {
      const s = rows.reduce<number>((acc, r) => {
        const v = col.num!(r)
        return acc + (typeof v === "number" ? v : 0)
      }, 0)
      const synthetic =
        col.header === "Profit" || col.header === "Revenue"
          ? { profit: s, revenue: s }
          : { loads: s }
      totals[idx] = col.value(synthetic as Record<string, unknown>)
    } else if (col.totalsRole === "marginPct") {
      let p = 0
      let rev = 0
      for (const r of rows) {
        if (typeof r.profit === "number") p += r.profit
        if (typeof r.revenue === "number") rev += r.revenue
      }
      const synthetic = { margin_pct: rev > 0 ? p / rev : null }
      totals[idx] = col.value(synthetic)
    }
  })

  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white">
      <div
        className="flex items-baseline justify-between border-b px-3 py-2"
        style={{ borderColor: `${accent}33`, backgroundColor: `${accent}0D` }}
      >
        <h3 className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: accent }}>
          {title}
        </h3>
        <span className="text-[10px] font-medium uppercase tracking-wider text-[#6B7280]">
          {subtitle}
        </span>
      </div>
      <table className="w-full border-separate border-spacing-0 text-xs">
        <thead className="bg-[#F9FAFB] text-[#374151]">
          <tr>
            <th className="border-b border-[#E5E7EB] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wider w-6">
              #
            </th>
            {columns.map((c, i) => (
              <th
                key={i}
                className={`border-b border-[#E5E7EB] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider ${
                  c.align === "right" ? "text-right" : "text-left"
                }`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {/* Totals row at top -- sum/margin% of the displayed top-3 */}
          <tr className="bg-[#FEF7E6]">
            <td className="border-b border-[#F3F4F6] px-2 py-1.5" />
            {columns.map((c, i) => (
              <td
                key={i}
                className={`border-b border-[#F3F4F6] px-3 py-1.5 font-semibold tabular-nums ${
                  c.align === "right" ? "text-right" : "text-left"
                }`}
              >
                {i === 0 ? "Totals" : (totals[i] ?? "")}
              </td>
            ))}
          </tr>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length + 1}
                className="px-3 py-6 text-center text-xs text-[#9CA3AF]"
              >
                No data yet.
              </td>
            </tr>
          ) : (
            rows.map((r, idx) => (
              <tr
                key={`${(r.posted_by as string) ?? "?"}-${idx}`}
                className="odd:bg-white even:bg-[#FAFBFC]"
              >
                <td className="border-b border-[#F3F4F6] px-2 py-1.5 text-center">
                  <span title={`Rank ${idx + 1}`}>{MEDALS[idx] ?? ""}</span>
                </td>
                {columns.map((c, i) => (
                  <td
                    key={i}
                    className={`border-b border-[#F3F4F6] px-3 py-1.5 text-[#111827] tabular-nums ${
                      c.align === "right" ? "text-right" : "text-left"
                    }`}
                  >
                    {c.value(r)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
