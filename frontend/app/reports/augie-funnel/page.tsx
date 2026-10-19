"use client"

import { Suspense, useCallback, useMemo } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Loader2, Workflow } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import {
  useAugieByTeam,
  useAugieFilterOptions,
  useAugieFreshness,
  useAugieLoads,
  useAugieSummary,
  useAugieTrend,
  type AugieFunnelFilters,
  type AugieFunnelGrain,
  type AugieFunnelNode,
  type AugieFunnelRange,
  type AugieFunnelSort,
  type AugieFunnelUnit,
} from "@/lib/augie-funnel-api"
import { FilterBar, RANGES, type FilterState } from "./FilterBar"
import { FunnelFlow } from "./FunnelFlow"
import { TrendChart } from "./TrendChart"
import { TeamTable } from "./TeamTable"
import { LoadsTable } from "./LoadsTable"
import { FreshnessLine, HowCounted } from "./Notes"
import { ErrorBlock, LoadingBlock, Panel } from "./Ui"

const NODES: AugieFunnelNode[] = [
  "all", "tracked", "contacted", "captured", "tracked_no_info", "not_tracked",
  "canceled", "international", "multistop", "not_covered", "other",
]
const SORTS: AugieFunnelSort[] = [
  "pickup_desc", "pickup_asc", "order_asc", "customer_asc", "carrier_asc", "team_asc",
  "stage_asc",
]

/** Whitelist a URL value — a hand-edited/stale URL must fall back, never 400. */
function pick<T extends string>(raw: string | null, allowed: readonly T[], dflt: T): T {
  return raw && (allowed as readonly string[]).includes(raw) ? (raw as T) : dflt
}

// URL keys: one place, so read and write cannot drift apart.
const K = {
  range: "range", s: "s", e: "e", unit: "unit", team: "team",
  customer: "cu", carrier: "ca", q: "q", node: "node", sort: "sort", grain: "grain",
} as const

function useUrlState() {
  const sp = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  const update = useCallback(
    (patch: Record<string, string | string[] | null | undefined>) => {
      const next = new URLSearchParams(sp.toString())
      for (const [k, v] of Object.entries(patch)) {
        next.delete(k)
        if (Array.isArray(v)) for (const item of v) next.append(k, item)
        else if (v) next.set(k, v)
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [sp, router, pathname],
  )
  return { sp, update }
}

function Content() {
  const { sp, update } = useUrlState()

  const range = pick<AugieFunnelRange>(sp.get(K.range), RANGES.map((r) => r.k), "today")
  const unitRaw = sp.get(K.unit)
  const unit: AugieFunnelUnit | "" = unitRaw === "CORP" || unitRaw === "DFW" ? unitRaw : ""
  const node = pick(sp.get(K.node), NODES, "all")
  const sort = pick(sp.get(K.sort), SORTS, "pickup_desc")
  const grain = pick<AugieFunnelGrain>(sp.get(K.grain), ["day", "week"], "day")
  const startDate = sp.get(K.s) ?? ""
  const endDate = sp.get(K.e) ?? ""
  const team = sp.get(K.team) ?? ""
  const q = sp.get(K.q) ?? ""
  // `getAll` returns a new array every render — key the memo on joined strings.
  const cuKey = sp.getAll(K.customer).join("\u0001")
  const caKey = sp.getAll(K.carrier).join("\u0001")

  const state: FilterState = useMemo(
    () => ({
      range, startDate, endDate, unit, team, q,
      customer: cuKey ? cuKey.split("\u0001") : [],
      carrier: caKey ? caKey.split("\u0001") : [],
    }),
    [range, startDate, endDate, unit, team, q, cuKey, caKey],
  )

  const filters: AugieFunnelFilters = useMemo(
    () => ({
      range: state.range,
      startDate: state.startDate || undefined,
      endDate: state.endDate || undefined,
      unit: state.unit ? [state.unit] : [],
      team: state.team ? [state.team] : [],
      customer: state.customer,
      carrier: state.carrier,
      q: state.q,
    }),
    [state],
  )

  const onFilters = (patch: Partial<FilterState>) => {
    const map: Record<string, string | string[] | null> = {}
    if ("range" in patch) map[K.range] = patch.range ?? null
    if ("startDate" in patch) map[K.s] = patch.startDate ?? null
    if ("endDate" in patch) map[K.e] = patch.endDate ?? null
    if ("unit" in patch) map[K.unit] = patch.unit ?? null
    if ("team" in patch) map[K.team] = patch.team ?? null
    if ("customer" in patch) map[K.customer] = patch.customer ?? []
    if ("carrier" in patch) map[K.carrier] = patch.carrier ?? []
    if ("q" in patch) map[K.q] = (patch.q ?? "").trim() || null
    update(map)
  }

  const options = useAugieFilterOptions()
  const fresh = useAugieFreshness()
  const summary = useAugieSummary(filters)
  const trend = useAugieTrend(filters, grain)
  const byTeam = useAugieByTeam(filters)
  const loads = useAugieLoads(filters, node, sort)

  const s = summary.data
  const singleDay = s
    ? s.start_date === s.end_date
    : range === "today" || (range === "custom" && startDate !== "" && startDate === endDate)
  const customIncomplete = range === "custom" && !(startDate && endDate)
  const windowLabel = !s
    ? ""
    : s.start_date === s.end_date
      ? s.start_date
      : `${s.start_date} → ${s.end_date}`

  return (
    <div className="mx-auto max-w-[1600px] space-y-4 bg-[#F9FAFB] p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[#E5E7EB] bg-white text-[#6B7280] hover:bg-[#F3F4F6]"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <Workflow className="h-5 w-5 shrink-0 text-[#9CA3AF]" />
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-[#111827]">Funnel Augie Activities</h1>
            <p className="text-xs text-[#6B7280]">
              Every load picked up, how many were sent to Augie, how many carriers gave an
              update — and why the rest were not sent.
            </p>
          </div>
        </div>
        {summary.isFetching ? <Loader2 className="h-4 w-4 animate-spin text-[#9CA3AF]" /> : null}
      </div>

      <FreshnessLine data={fresh.data} error={fresh.error} />
      <FilterBar value={state} options={options.data} onChange={onFilters} />
      {options.error ? <ErrorBlock what="the filter lists" error={options.error} /> : null}

      {customIncomplete ? (
        <p className="rounded-lg border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2 text-xs text-[#92400E]">
          Pick both a start and an end date for the custom range.
        </p>
      ) : (
        <>
          <Panel
            title="From pickup to carrier update"
            subtitle={windowLabel ? `Loads picked up ${windowLabel} (CST)` : undefined}
          >
            {summary.error ? (
              <ErrorBlock what="the funnel" error={summary.error} />
            ) : s ? (
              <FunnelFlow
                data={s}
                node={node}
                onNode={(n) => update({ [K.node]: n === "all" ? null : n })}
              />
            ) : (
              <LoadingBlock h={220} />
            )}
          </Panel>

          <LoadsTable
            data={loads.data}
            loading={loads.isLoading}
            error={loads.error}
            node={node}
            onClearNode={() => update({ [K.node]: null })}
            sort={sort}
            onSort={(v) => update({ [K.sort]: v === "pickup_desc" ? null : v })}
          />

          <TrendChart
            data={trend.data}
            grain={grain}
            onGrainChange={(g) => update({ [K.grain]: g === "day" ? null : g })}
            loading={trend.isLoading}
            error={trend.error}
            singleDay={singleDay}
          />

          <TeamTable rows={byTeam.data} loading={byTeam.isLoading} error={byTeam.error} />
        </>
      )}

      <HowCounted />
    </div>
  )
}

export default function Page() {
  return (
    <ReportGuard reportKey="augie-funnel">
      <Suspense
        fallback={
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        }
      >
        <Content />
      </Suspense>
    </ReportGuard>
  )
}
