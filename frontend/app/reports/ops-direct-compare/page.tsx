"use client"

import { Suspense, useCallback, useMemo } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, GitCompareArrows, Loader2 } from "lucide-react"
import {
  computeDelta,
  useDCFilters,
  useDCFreshness,
  useDCPanelSummary,
  type DCDivision,
  type DCPanelFilters,
  type DCRange,
} from "@/lib/ops-direct-compare-api"
import { fmtTimestamp } from "../ops-margins/format"
import { KpiCards } from "./KpiCards"
import { PanelFilters } from "./PanelFilters"
import { ConcentrationPie } from "./sections/ConcentrationPie"
import { CustomerRevMarginCombo } from "./sections/CustomerRevMarginCombo"
import { CustomerTable } from "./sections/CustomerTable"
import { LaneTable } from "./sections/LaneTable"
import { OrdersTable } from "./sections/OrdersTable"
import { Trend12m } from "./sections/Trend12m"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"

const YEAR_START = "2026-01-01"
const YEAR_END = "2026-12-31"
const ALL_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW"] as const
const DFW_SUB_TEAMS = ["TM1", "TM2", "TM3", "TM4"] as const

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`
}
function monthStartIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`
}
function clampToYear(iso: string) {
  if (iso < YEAR_START) return YEAR_START
  if (iso > YEAR_END) return YEAR_END
  return iso
}

interface PanelState {
  range: DCRange
  startDate: string
  endDate: string
  division: DCDivision
  teams: string[]
  subTeams: string[]
}

function readPanel(
  searchParams: URLSearchParams,
  prefix: "p1" | "p2",
  defaults: { range: DCRange; startDate: string; endDate: string },
): PanelState {
  const rawRange = searchParams.get(`${prefix}_r`) as DCRange | null
  const range: DCRange = (["mtd", "last_month", "ytd", "custom"] as const).includes(
    rawRange as DCRange,
  )
    ? (rawRange as DCRange)
    : defaults.range
  const startDate = clampToYear(searchParams.get(`${prefix}_s`) || defaults.startDate)
  const endDate = clampToYear(searchParams.get(`${prefix}_e`) || defaults.endDate)
  const divRaw = (searchParams.get(`${prefix}_d`) || "All") as DCDivision
  const division: DCDivision = ["All", "CORP", "DFW"].includes(divRaw) ? divRaw : "All"
  const teamsParam = searchParams.get(`${prefix}_t`)
  const teams =
    teamsParam === null
      ? [...ALL_TEAMS]
      : teamsParam === ""
        ? []
        : teamsParam
            .split(",")
            .filter((t) => (ALL_TEAMS as readonly string[]).includes(t))
  const subParam = searchParams.get(`${prefix}_sub`)
  const subTeams =
    !subParam || division !== "DFW"
      ? []
      : subParam.split(",").filter((t) => (DFW_SUB_TEAMS as readonly string[]).includes(t))
  return { range, startDate, endDate, division, teams, subTeams }
}

function panelToFilters(p: PanelState): DCPanelFilters {
  return {
    range: p.range,
    startDate: p.range === "custom" ? p.startDate : undefined,
    endDate: p.range === "custom" ? p.endDate : undefined,
    division: p.division,
    teams: p.teams.length === ALL_TEAMS.length ? undefined : p.teams,
    subTeams: p.division === "DFW" && p.subTeams.length ? p.subTeams : undefined,
  }
}

function lastMonthRange(): { start: string; end: string } {
  const today = new Date()
  const firstOfThisMonth = new Date(today.getFullYear(), today.getMonth(), 1)
  const lastOfPrev = new Date(firstOfThisMonth.getTime() - 86400000)
  const firstOfPrev = new Date(lastOfPrev.getFullYear(), lastOfPrev.getMonth(), 1)
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
  return { start: iso(firstOfPrev), end: iso(lastOfPrev) }
}

function DirectCompareContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  const lastMo = lastMonthRange()
  const p1 = readPanel(searchParams, "p1", {
    range: "mtd",
    startDate: monthStartIso(),
    endDate: clampToYear(todayIso()),
  })
  const p2 = readPanel(searchParams, "p2", {
    range: "last_month",
    startDate: lastMo.start,
    endDate: lastMo.end,
  })

  const updateUrl = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      const next = new URLSearchParams(searchParams.toString())
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === undefined) next.delete(k)
        else next.set(k, v)
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [searchParams, router, pathname],
  )

  const setPanelRange = (prefix: "p1" | "p2", r: DCRange) =>
    updateUrl({ [`${prefix}_r`]: r === (prefix === "p1" ? "mtd" : "last_month") ? null : r })
  const setPanelStart = (prefix: "p1" | "p2", d: string) =>
    updateUrl({ [`${prefix}_s`]: d })
  const setPanelEnd = (prefix: "p1" | "p2", d: string) =>
    updateUrl({ [`${prefix}_e`]: d })
  const setPanelDivision = (prefix: "p1" | "p2", d: DCDivision) =>
    updateUrl({
      [`${prefix}_d`]: d === "All" ? null : d,
      [`${prefix}_t`]: null,
      [`${prefix}_sub`]: null,
    })
  const togglePanelTeam = (prefix: "p1" | "p2", state: PanelState, t: string) => {
    const next = state.teams.includes(t)
      ? state.teams.filter((x) => x !== t)
      : [...state.teams, t]
    updateUrl({
      [`${prefix}_t`]: next.length === ALL_TEAMS.length ? null : next.join(","),
    })
  }
  const togglePanelSubTeam = (prefix: "p1" | "p2", state: PanelState, st: string) => {
    const next = state.subTeams.includes(st)
      ? state.subTeams.filter((x) => x !== st)
      : [...state.subTeams, st]
    updateUrl({ [`${prefix}_sub`]: next.length === 0 ? null : next.join(",") })
  }

  const f1 = useMemo(() => panelToFilters(p1), [p1])
  const f2 = useMemo(() => panelToFilters(p2), [p2])

  const { data: filtersRes, isLoading: loadingFilters } = useDCFilters()
  const opts = filtersRes?.data
  const yearStart = opts?.year_start ?? YEAR_START
  const yearEnd = opts?.year_end ?? YEAR_END

  const sum1 = useDCPanelSummary("p1", f1)
  const sum2 = useDCPanelSummary("p2", f2)
  const delta = computeDelta(sum1.data?.data, sum2.data?.data)

  const { data: freshnessRes } = useDCFreshness()
  const fr = freshnessRes?.data

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Mobile gate — desktop-only (side-by-side comparison) */}
      <div className="border-b border-[#FDE68A] bg-[#FEF3C7] px-4 py-2 text-xs text-[#92400E] xl:hidden">
        <strong>Best viewed on desktop.</strong> OPs Direct Compare shows two side-by-side
        panels and dense diff tables; mobile rendering is limited.
      </div>

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
          <GitCompareArrows className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">OPs Direct Compare</h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-[10px] text-[#1E40AF]">
            side-by-side
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          {fr?.last_updated && (
            <span
              className="rounded-full bg-[#F3F4F6] px-2 py-0.5 text-[10px] text-[#374151]"
              title={`Source: mcleod_gld_budget_report_v4 · ${fr.rows_in_scope.toLocaleString()} rows in scope`}
            >
              Data refreshed: {fmtTimestamp(fr.last_updated)}
            </span>
          )}
        </div>
      </div>

      {loadingFilters ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="mx-auto w-full max-w-[1920px] space-y-4 px-4 py-4">
          {/* Top row: filter bars side-by-side */}
          <div className="grid grid-cols-2 gap-4">
            <PanelFilters
              label="Panel 1 (data1)"
              accent="blue"
              yearStart={yearStart}
              yearEnd={yearEnd}
              range={p1.range}
              startDate={p1.startDate}
              endDate={p1.endDate}
              division={p1.division}
              teams={p1.teams}
              subTeams={p1.subTeams}
              onRange={(r) => setPanelRange("p1", r)}
              onStartDate={(d) => setPanelStart("p1", d)}
              onEndDate={(d) => setPanelEnd("p1", d)}
              onDivision={(d) => setPanelDivision("p1", d)}
              onToggleTeam={(t) => togglePanelTeam("p1", p1, t)}
              onToggleSubTeam={(st) => togglePanelSubTeam("p1", p1, st)}
            />
            <PanelFilters
              label="Panel 2 (data2)"
              accent="violet"
              yearStart={yearStart}
              yearEnd={yearEnd}
              range={p2.range}
              startDate={p2.startDate}
              endDate={p2.endDate}
              division={p2.division}
              teams={p2.teams}
              subTeams={p2.subTeams}
              onRange={(r) => setPanelRange("p2", r)}
              onStartDate={(d) => setPanelStart("p2", d)}
              onEndDate={(d) => setPanelEnd("p2", d)}
              onDivision={(d) => setPanelDivision("p2", d)}
              onToggleTeam={(t) => togglePanelTeam("p2", p2, t)}
              onToggleSubTeam={(st) => togglePanelSubTeam("p2", p2, st)}
            />
          </div>

          {/* KPI row: panel1 / delta / panel2 */}
          <div className="grid grid-cols-3 gap-4">
            <KpiCards variant="p1" values={sum1.data?.data ?? null} loading={sum1.isLoading} />
            <KpiCards variant="delta" values={delta} loading={sum1.isLoading || sum2.isLoading} />
            <KpiCards variant="p2" values={sum2.data?.data ?? null} loading={sum2.isLoading} />
          </div>

          {/* Always-on 12-month trend (filter-less) */}
          <Trend12m variant="full" title="Monthly end-to-Month — $Profit, $Revenue, % Margin · last 12 months" />

          {/* Concentration pies side-by-side */}
          <div className="grid grid-cols-2 gap-4">
            <ConcentrationPie panel="p1" filters={f1} title="(1) % Customer concentration by Profit — Top 5" />
            <ConcentrationPie panel="p2" filters={f2} title="(2) % Customer concentration by Profit — Top 5" />
          </div>

          {/* Customer detail tables */}
          <div className="grid grid-cols-2 gap-4">
            <CustomerTable
              title="(1) Details by Customer"
              panel="p1"
              panelFilters={f1}
            />
            <CustomerTable
              title="(2) Details by Customer · with Diff vs Panel 1"
              panel="p2"
              panelFilters={f2}
              diffAgainst={f1}
            />
          </div>

          {/* Lane detail tables */}
          <div className="grid grid-cols-2 gap-4">
            <LaneTable title="(1) Details by Lane" panel="p1" panelFilters={f1} />
            <LaneTable
              title="(2) Details by Lane · with Diff vs Panel 1"
              panel="p2"
              panelFilters={f2}
              diffAgainst={f1}
            />
          </div>

          {/* Trend (panel-2 view) + Combo */}
          <Trend12m variant="profit-only" title="Monthly end-to-Month — $Profit & % Margin · last 12 months" />
          <CustomerRevMarginCombo
            filters={f2}
            title="(2) By Customer Details — $Revenue & % Margin"
          />

          {/* Orders detail (this year + last year) */}
          <OrdersTable
            filters={f2}
            title="(2) Details by Order — this year + last year (filter: Panel 2 division/team)"
          />
        </div>
      )}
    </div>
  )
}

export default function OpsDirectComparePage() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["ops-direct-compare"]]}>
      <Suspense
        fallback={
          <div className="flex min-h-[calc(100vh-64px)] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
          </div>
        }
      >
        <DirectCompareContent />
      </Suspense>
    </RoleGuard>
  )
}
