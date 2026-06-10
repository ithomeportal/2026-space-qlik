"use client"

import { useState } from "react"
import Link from "next/link"
import { ArrowLeft, Loader2, Search, Trophy, X } from "lucide-react"
import {
  usePodiumTop,
  type BookerGroup,
  type PodiumLeaderboards,
} from "@/lib/podium-top-api"
import { fmtCurrency, fmtInt, fmtPct } from "@/lib/podium-dfw-api"
import { useDebounce } from "@/lib/use-debounce"
import { ReportGuard } from "@/components/ReportGuard"

// Shared body for "DFW Podium Top" and its four server-locked per-team
// variants (Bruno R7, 2026-06-02). The main report passes no team; each
// per-team route passes apiPrefix=custom/dfw-podium-top-tmN.
export function DfwPodiumTopContent({
  reportKey,
  apiPrefix,
  title,
}: {
  reportKey: string
  apiPrefix: string
  title: string
}) {
  return (
    <ReportGuard reportKey={reportKey}>
      <Body apiPrefix={apiPrefix} title={title} />
    </ReportGuard>
  )
}

function Body({ apiPrefix, title }: { apiPrefix: string; title: string }) {
  // Equipment Type filter (R8) — server-side contains match; all leaderboards
  // recompute over only the matching loads. Debounced so typing doesn't fire
  // a request per keystroke.
  const [equipment, setEquipment] = useState("")
  const debouncedEquipment = useDebounce(equipment, 300)
  // Bruno R1 (2026-06-09): "Bookers" roster (default) vs "All DFW".
  const [group, setGroup] = useState<BookerGroup>("bookers")
  const q = usePodiumTop(apiPrefix, debouncedEquipment, group)
  const data = q.data?.data
  const equipmentActive = debouncedEquipment.trim() !== ""
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
          <h1 className="text-sm font-semibold text-[#1B3A5C]">{title}</h1>
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
            Failed to load {title} data.
            {q.error instanceof Error ? ` (${q.error.message})` : ""}
          </div>
        ) : null}

        {/* Group toggle (R1) + Equipment Type filter (R8) */}
        <section className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-2.5">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
                Group
              </span>
              <div className="flex rounded-md border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
                {[
                  { k: "bookers" as const, label: "Bookers" },
                  { k: "all" as const, label: "All DFW" },
                ].map((opt) => (
                  <button
                    key={opt.k}
                    type="button"
                    onClick={() => setGroup(opt.k)}
                    className={`px-3 py-1.5 ${
                      group === opt.k
                        ? "rounded-md bg-white font-semibold text-[#1B3A5C] shadow-sm"
                        : "text-[#6B7280] hover:text-[#111827]"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
            <label className="flex min-w-[180px] flex-col gap-1 md:max-w-[280px]">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
                Equipment Type
              </span>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#9CA3AF]" />
                <input
                  type="text"
                  value={equipment}
                  onChange={(e) => setEquipment(e.target.value)}
                  placeholder="Search equipment…"
                  className="w-full rounded-md border border-[#E5E7EB] bg-white py-1.5 pl-7 pr-7 text-xs text-[#111827] placeholder:text-[#9CA3AF] focus:border-[#1B3A5C] focus:outline-none focus:ring-1 focus:ring-[#1B3A5C]"
                />
                {equipment !== "" && (
                  <button
                    onClick={() => setEquipment("")}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-[#9CA3AF] hover:bg-[#F3F4F6] hover:text-[#374151]"
                    aria-label="Clear Equipment Type filter"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </label>
            {equipmentActive && (
              <p className="pb-1.5 text-[11px] text-[#6B7280]">
                Leaderboards reflect only loads whose equipment matches
                &ldquo;{debouncedEquipment.trim()}&rdquo;.
              </p>
            )}
          </div>
        </section>

        <Podiums data={data} loading={q.isLoading} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Podium leaderboards.
//   This Week: top-3 tables (Bruno R6 "keep unchanged").
//   Today:     full lists (Bruno R6 removed the top-3 display limit).
// Totals row = sum of just the displayed rows.
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
          title="Best Profit This Week"
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
          title="Best Loads This Week"
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
          columns={[postedByCol, loadsCol, profitCol]}
        />
        <PodiumTable
          title="TOP Bookers by Profit"
          subtitle="Today"
          rows={data.today_top_profit as unknown as Record<string, unknown>[]}
          accent="#C2410C"
          columns={[postedByCol, profitCol, loadsCol]}
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
  // Totals row -- sum / margin% of the displayed rows.
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
          {/* Totals row at top -- sum / margin% of the displayed rows */}
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
                <td className="border-b border-[#F3F4F6] px-2 py-1.5 text-center tabular-nums text-[#6B7280]">
                  {/* Medal for the top 3, plain rank number beyond (R6: full list) */}
                  <span title={`Rank ${idx + 1}`}>{MEDALS[idx] ?? idx + 1}</span>
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
