"use client"

import { Suspense, useCallback, useMemo } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Loader2, PieChart } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import { MultiSelectChips } from "@/components/MultiSelectChips"
import {
  useSpotsFilterOptions,
  useSpotsFreshness,
  type SpotsDim,
  type SpotsFilters,
  type SpotsGrain,
  type SpotsRange,
  type SpotsSort,
} from "@/lib/production-spots-trends-api"
import { KpiCards } from "./KpiCards"
import { ComparePanel } from "./ComparePanel"
import { FunnelPanel } from "./FunnelPanel"
import { TrendChart } from "./TrendChart"
import { BreakdownTable } from "./BreakdownTable"
import { ActualsPanel } from "./ActualsPanel"
import { Note } from "./Ui"

// April 2026 is the first month clear of the frozen legacy imports — see the
// router docstring. Earlier ranges would be truthfully but confusingly thin.
const DATA_FLOOR = "2026-04-01"
const YEAR_END = "2026-12-31"

const RANGES: { k: SpotsRange; label: string }[] = [
  { k: "today", label: "Today" },
  { k: "wtd", label: "WTD" },
  { k: "last7", label: "7d" },
  { k: "mtd", label: "MTD" },
  { k: "last_month", label: "Last month" },
  { k: "last30", label: "30d" },
  { k: "last90", label: "90d" },
  { k: "qtd", label: "QTD" },
  { k: "ytd", label: "YTD" },
  { k: "custom", label: "Custom" },
]

const GRAINS: SpotsGrain[] = ["day", "week", "month"]

const TABS = [
  { k: "overview", label: "Overview" },
  { k: "funnel", label: "Funnel" },
  { k: "channels", label: "Channels" },
  { k: "customers", label: "Customers" },
  { k: "team", label: "Team & AUTO-BOT" },
  { k: "actuals", label: "Moved (Actuals)" },
] as const

type TabKey = (typeof TABS)[number]["k"]

const TAB_DIM: Partial<Record<TabKey, SpotsDim>> = {
  channels: "channel",
  customers: "customer",
  team: "actor",
}

function pad(n: number) {
  return String(n).padStart(2, "0")
}
function iso(d: Date) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function clamp(v: string) {
  if (v < DATA_FLOOR) return DATA_FLOOR
  if (v > YEAR_END) return YEAR_END
  return v
}

function Content() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  const range = (searchParams.get("range") as SpotsRange) || "mtd"
  const grain = (searchParams.get("grain") as SpotsGrain) || "day"
  const tab = (searchParams.get("tab") as TabKey) || "overview"
  const sort = (searchParams.get("sort") as SpotsSort) || "presented_desc"
  const startDate = clamp(searchParams.get("s") || iso(new Date()).slice(0, 8) + "01")
  const endDate = clamp(searchParams.get("e") || iso(new Date()))
  const channel = searchParams.getAll("ch")
  const customer = searchParams.getAll("cu")
  const actor = searchParams.getAll("ac")
  const equipment = searchParams.getAll("eq")
  const division = searchParams.getAll("dv")

  const { data: optsRes, isLoading: loadingFilters } = useSpotsFilterOptions()
  const { data: freshRes } = useSpotsFreshness()
  const opts = optsRes?.data
  const fresh = freshRes?.data

  const updateUrl = useCallback(
    (patch: Record<string, string | string[] | null | undefined>) => {
      const next = new URLSearchParams(searchParams.toString())
      for (const [k, v] of Object.entries(patch)) {
        next.delete(k)
        if (Array.isArray(v)) for (const item of v) next.append(k, item)
        else if (v !== null && v !== undefined && v !== "") next.set(k, v)
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [searchParams, router, pathname]
  )

  // Hoisted so the dependency array holds plain values: `searchParams.getAll`
  // returns a NEW array every render, so depending on the arrays themselves
  // would rebuild `filters` on every render and refire every query.
  const chKey = channel.join("|")
  const cuKey = customer.join("|")
  const acKey = actor.join("|")
  const eqKey = equipment.join("|")
  const dvKey = division.join("|")

  const filters: SpotsFilters = useMemo(
    () => ({ range, startDate, endDate, channel, customer, actor, equipment, division }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [range, startDate, endDate, chKey, cuKey, acKey, eqKey, dvKey]
  )

  const windowLabel = useMemo(() => {
    if (range === "custom") return `${startDate} → ${endDate}`
    return RANGES.find((r) => r.k === range)?.label ?? ""
  }, [range, startDate, endDate])

  const dim = TAB_DIM[tab]

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Top bar */}
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
          <PieChart className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">
            Production SPOTS Trends
          </h1>
          <span className="rounded-full bg-[#E0E7FF] px-2 py-0.5 text-xs text-[#4338CA]">
            All spot sources
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          <span>{windowLabel}</span>
          {/* A page over a synced table needs a visible freshness signal, or a
              dead pipeline and a quiet day look identical (§54). */}
          {fresh?.spot ? (
            <span
              className={
                fresh.is_stale
                  ? "rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[#92400E]"
                  : ""
              }
              title={fresh.feeds
                .map(
                  (f) =>
                    `${f.source}: ${f.heartbeat?.slice(0, 16).replace("T", " ") ?? "no heartbeat"}`
                )
                .join(" · ")}
            >
              Data as of {fresh.spot.slice(0, 16).replace("T", " ")}
              {fresh.is_stale ? " · stale" : ""}
            </span>
          ) : null}
        </div>
      </div>

      {/* Sticky filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Date
            </label>
            <div className="flex flex-wrap rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {RANGES.map((opt) => (
                <button
                  key={opt.k}
                  onClick={() => updateUrl({ range: opt.k === "mtd" ? null : opt.k })}
                  className={`px-2.5 py-1.5 ${
                    range === opt.k
                      ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                      : "text-[#6B7280] hover:text-[#111827]"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {range === "custom" && (
              <div className="flex items-center gap-1 text-xs">
                <input
                  type="date"
                  min={opts?.data_floor ?? DATA_FLOOR}
                  max={YEAR_END}
                  value={startDate}
                  onChange={(ev) => updateUrl({ s: ev.target.value })}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
                <span className="text-[#6B7280]">→</span>
                <input
                  type="date"
                  min={opts?.data_floor ?? DATA_FLOOR}
                  max={YEAR_END}
                  value={endDate}
                  onChange={(ev) => updateUrl({ e: ev.target.value })}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Grain
            </label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {GRAINS.map((g) => (
                <button
                  key={g}
                  onClick={() => updateUrl({ grain: g === "day" ? null : g })}
                  className={`px-3 py-1.5 capitalize ${
                    grain === g
                      ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                      : "text-[#6B7280] hover:text-[#111827]"
                  }`}
                >
                  {g}
                </button>
              ))}
            </div>
          </div>

          <MultiSelectChips
            label="Channel"
            options={opts?.channels ?? []}
            selected={channel}
            onChange={(v: string[]) => updateUrl({ ch: v })}
            placeholder="All channels"
            width={190}
            disabled={loadingFilters}
          />
          <MultiSelectChips
            label="Customer"
            options={opts?.customers ?? []}
            selected={customer}
            onChange={(v: string[]) => updateUrl({ cu: v })}
            placeholder="All customers"
            width={230}
            disabled={loadingFilters}
          />
          <MultiSelectChips
            label="Person / bot"
            options={opts?.actors ?? []}
            selected={actor}
            onChange={(v: string[]) => updateUrl({ ac: v })}
            placeholder="Everyone"
            width={200}
            disabled={loadingFilters}
          />
          <MultiSelectChips
            label="Equipment"
            options={opts?.equipment ?? []}
            selected={equipment}
            onChange={(v: string[]) => updateUrl({ eq: v })}
            placeholder="All equipment"
            width={180}
            disabled={loadingFilters}
          />
          <MultiSelectChips
            label="Division"
            options={opts?.divisions ?? []}
            selected={division}
            onChange={(v: string[]) => updateUrl({ dv: v })}
            placeholder="Both"
            width={160}
            disabled={loadingFilters}
          />
        </div>

        {/* Tabs */}
        <div className="mx-auto flex w-full max-w-[1920px] gap-1 overflow-x-auto px-6">
          {TABS.map((t) => (
            <button
              key={t.k}
              onClick={() =>
                updateUrl({ tab: t.k === "overview" ? null : t.k, sort: null })
              }
              className={`whitespace-nowrap border-b-2 px-3 py-2 text-xs ${
                tab === t.k
                  ? "border-[#1B3A5C] font-semibold text-[#1B3A5C]"
                  : "border-transparent text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] min-w-0 flex-1 space-y-4 px-6 py-6">
        <KpiCards filters={filters} />

        {tab === "overview" ? (
          <>
            <TrendChart filters={filters} grain={grain} />
            <ComparePanel filters={filters} />
          </>
        ) : null}

        {tab === "funnel" ? (
          <>
            <FunnelPanel filters={filters} />
            <TrendChart filters={filters} grain={grain} />
          </>
        ) : null}

        {dim ? (
          <>
            {tab === "team" ? (
              <Note>
                The external-portal agent recorded no wins at all before{" "}
                {opts?.bot_outcomes_from ?? "2026-09-21"} — an award event was
                unmapped and the historical wins were entered by hand on one day. A
                bot win rate measured across that date is not comparable, and reads
                pessimistically, which looks like &quot;the bot prices too high&quot;.
                Home Depot rows carry no person at all and appear as{" "}
                <strong>HD Auto-pricer</strong>; they are a machine feed, not an
                unknown human.
              </Note>
            ) : null}
            <BreakdownTable
              filters={filters}
              dim={dim}
              sort={sort}
              onSort={(s) => updateUrl({ sort: s })}
              note={
                tab === "customers"
                  ? "Home Depot appears under both the HD board and the lane feed; grouping by customer merges the two channels, grouping by channel splits them."
                  : tab === "channels"
                    ? "Autobot is the lane feed filed by agent:ops-external-spots (e2open, Princeton, Transporeon and RXO all share that one identity, so they cannot be split apart here). Manual is the rest of the lane feed. The Emerge/Trane board is not in this data source at all."
                    : undefined
              }
            />
            <TrendChart filters={filters} grain={grain} />
          </>
        ) : null}

        {tab === "actuals" ? <ActualsPanel filters={filters} grain={grain} /> : null}
      </div>
    </div>
  )
}

export default function ProductionSpotsTrendsPage() {
  return (
    <ReportGuard reportKey="production-spots-trends">
      <Suspense
        fallback={
          <div className="flex min-h-[calc(100vh-64px)] items-center justify-center bg-[#F9FAFB]">
            <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
          </div>
        }
      >
        <Content />
      </Suspense>
    </ReportGuard>
  )
}
