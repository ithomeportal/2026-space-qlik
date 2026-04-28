"use client"

import { Suspense, useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import {
  AlertTriangle,
  ArrowLeft,
  DollarSign,
  Loader2,
  ShieldAlert,
  Truck,
  Users,
  X,
} from "lucide-react"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"
import {
  useCarrierRiskFacets,
  useCarrierRiskKpis,
  type CarrierRiskFilters,
  type CarrierRiskRange,
} from "@/lib/carrier-risk-api"
import { LaneTable } from "./LaneTable"
import { CarrierLaneTable } from "./CarrierLaneTable"
import { DetailsTable } from "./DetailsTable"
import { fmtCount, fmtPct, fmtUsd } from "./format"

const ALL_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW"] as const

const RANGE_PRESETS: { k: CarrierRiskRange; label: string }[] = [
  { k: "mtd", label: "MTD" },
  { k: "last_month", label: "Last Month" },
  { k: "last_3m", label: "Last 90d" },
  { k: "ytd", label: "YTD" },
  { k: "custom", label: "Custom" },
]

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

function monthStartIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`
}

function CarrierRiskContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  // ---- URL state -----------------------------------------------------------
  const range = (searchParams.get("range") as CarrierRiskRange) || "mtd"
  const startDate = searchParams.get("s") || monthStartIso()
  const endDate = searchParams.get("e") || todayIso()
  const teamsParam = searchParams.get("teams")
  const teams = useMemo<string[]>(() => {
    if (teamsParam === null) return [...ALL_TEAMS]
    if (teamsParam === "") return []
    return teamsParam
      .split(",")
      .filter((t) => (ALL_TEAMS as readonly string[]).includes(t))
  }, [teamsParam])
  const customer = searchParams.get("customer") || ""
  const lane = searchParams.get("lane") || ""

  const laneSort = searchParams.get("lane_sort") || "n_mov_desc"
  const lanePage = Math.max(1, Number(searchParams.get("lane_page") || "1"))
  const carrierSort = searchParams.get("car_sort") || "mov_desc"
  const carrierPage = Math.max(1, Number(searchParams.get("car_page") || "1"))
  const detailsSort = searchParams.get("det_sort") || "departure_desc"
  const detailsPage = Math.max(1, Number(searchParams.get("det_page") || "1"))

  const updateUrl = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      const next = new URLSearchParams(searchParams.toString())
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === undefined || v === "") next.delete(k)
        else next.set(k, v)
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [searchParams, router, pathname],
  )

  const setRange = (r: CarrierRiskRange) => updateUrl({ range: r === "mtd" ? null : r, lane_page: null, car_page: null, det_page: null })
  const setStartDate = (d: string) => updateUrl({ s: d })
  const setEndDate = (d: string) => updateUrl({ e: d })
  const setCustomer = (c: string) => updateUrl({ customer: c || null, lane_page: null, car_page: null, det_page: null })
  const setLane = (l: string) => updateUrl({ lane: l || null, car_page: null, det_page: null })
  const setTeams = (next: string[]) => {
    if (next.length === ALL_TEAMS.length) updateUrl({ teams: null })
    else updateUrl({ teams: next.join(",") })
    updateUrl({ lane_page: null, car_page: null, det_page: null })
  }
  const toggleTeam = (t: string) => {
    setTeams(teams.includes(t) ? teams.filter((x) => x !== t) : [...teams, t])
  }
  const allTeamsSelected = teams.length === ALL_TEAMS.length

  const filters: CarrierRiskFilters = useMemo(
    () => ({
      range,
      startDate: range === "custom" ? startDate : undefined,
      endDate: range === "custom" ? endDate : undefined,
      teams,
      customer: customer || undefined,
      lane: lane || undefined,
    }),
    [range, startDate, endDate, teams, customer, lane],
  )

  // ---- Data ---------------------------------------------------------------
  const { data: facetsRes } = useCarrierRiskFacets()
  const facets = facetsRes?.data
  const { data: kpisRes, isLoading: loadingKpis } = useCarrierRiskKpis(filters)
  const k = kpisRes?.data

  const [customerInput, setCustomerInput] = useState<string>("")
  const customerSuggestions = useMemo(() => {
    const q = customerInput.trim().toLowerCase()
    if (!q || !facets?.customers) return []
    return facets.customers
      .filter((c) => c.toLowerCase().includes(q))
      .slice(0, 8)
  }, [customerInput, facets])

  const windowLabel = k?.window
    ? `${k.window.start} → ${k.window.end}`
    : range.replace("_", " ").toUpperCase()

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
          <ShieldAlert className="h-4 w-4 text-[#B45309]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">Risk Asss for Carriers</h1>
          <span className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[10px] text-[#92400E]">
            concentration risk
          </span>
        </div>
        <div className="ml-auto text-xs text-[#6B7280]">
          {windowLabel}
          {" · "}Teams: {allTeamsSelected ? "All" : teams.join(", ") || "None"}
          {" · "}Customer: {customer || "All"}
          {lane && (
            <>
              {" · "}Lane: <span className="text-[#1B3A5C]">{lane}</span>
            </>
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          {/* Range */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Range
            </label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {RANGE_PRESETS.map((opt) => (
                <button
                  key={opt.k}
                  onClick={() => setRange(opt.k)}
                  className={`px-3 py-1.5 ${
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
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
                <span className="text-[#6B7280]">→</span>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
              </div>
            )}
          </div>

          {/* Teams */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Teams
            </label>
            <div className="flex flex-wrap gap-1">
              {ALL_TEAMS.map((t) => {
                const active = teams.includes(t)
                return (
                  <button
                    key={t}
                    onClick={() => toggleTeam(t)}
                    className={`rounded-full px-2.5 py-1 text-xs ${
                      active
                        ? "bg-[#1B3A5C] text-white"
                        : "border border-[#E5E7EB] text-[#374151] hover:bg-[#F9FAFB]"
                    }`}
                  >
                    {t}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Customer (with autosuggest from facets) */}
          <div className="relative flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Customer
            </label>
            <input
              type="text"
              value={customer || customerInput}
              placeholder="Type to filter…"
              onChange={(e) => {
                setCustomerInput(e.target.value)
                if (!e.target.value) setCustomer("")
              }}
              className="w-56 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            />
            {customer && (
              <button
                onClick={() => {
                  setCustomer("")
                  setCustomerInput("")
                }}
                className="rounded-md p-1 text-[#6B7280] hover:bg-[#F9FAFB]"
                title="Clear customer"
              >
                <X className="h-3 w-3" />
              </button>
            )}
            {customerSuggestions.length > 0 && !customer && (
              <div className="absolute left-[80px] top-7 z-20 max-h-60 w-56 overflow-auto rounded-md border border-[#E5E7EB] bg-white shadow-md">
                {customerSuggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => {
                      setCustomer(s)
                      setCustomerInput("")
                    }}
                    className="block w-full px-3 py-1.5 text-left text-xs hover:bg-[#F9FAFB]"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Lane chip */}
          {lane && (
            <div className="flex items-center gap-1 rounded-full bg-[#E0E7FF] px-3 py-1 text-xs text-[#3730A3]">
              <span className="font-medium">Lane:</span>
              <span>{lane}</span>
              <button
                onClick={() => setLane("")}
                className="ml-1 rounded-full hover:bg-[#C7D2FE]"
                title="Clear lane filter"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* KPI bar */}
      <div className="mx-auto w-full max-w-[1920px] px-6 py-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          <KpiCard
            icon={<Truck className="h-4 w-4 text-[#1B3A5C]" />}
            label="Movements"
            value={loadingKpis ? "…" : fmtCount(k?.movements)}
          />
          <KpiCard
            icon={<Users className="h-4 w-4 text-[#1B3A5C]" />}
            label="Distinct carriers"
            value={loadingKpis ? "…" : fmtCount(k?.distinct_carriers)}
          />
          <KpiCard
            label="Distinct lanes"
            value={loadingKpis ? "…" : fmtCount(k?.distinct_lanes)}
          />
          <KpiCard
            icon={<DollarSign className="h-4 w-4 text-[#1B3A5C]" />}
            label="Avg carrier cost"
            value={loadingKpis ? "…" : fmtUsd(k?.avg_carrier_cost)}
          />
          <KpiCard
            label="Total revenue"
            value={loadingKpis ? "…" : fmtUsd(k?.revenue)}
            sub={k && k.margin_pct !== null ? `Margin ${fmtPct(k.margin_pct)}` : undefined}
          />
          <KpiCard
            icon={<AlertTriangle className="h-4 w-4 text-[#B45309]" />}
            label="Single-carrier lanes"
            value={loadingKpis ? "…" : k?.single_carrier_lane_pct !== null && k?.single_carrier_lane_pct !== undefined ? fmtPct(k.single_carrier_lane_pct) : "—"}
            sub={k && k.single_carrier_volume_pct !== null ? `${fmtPct(k.single_carrier_volume_pct)} of volume` : undefined}
            warn
          />
        </div>

        {/* Tables */}
        <div className="mt-6 space-y-6">
          <LaneTable
            filters={filters}
            sort={laneSort as Parameters<typeof LaneTable>[0]["sort"]}
            page={lanePage}
            pageSize={50}
            onSortChange={(s) => updateUrl({ lane_sort: s, lane_page: null })}
            onPageChange={(p) => updateUrl({ lane_page: p === 1 ? null : String(p) })}
            onLaneClick={(l) => setLane(l)}
          />
          <CarrierLaneTable
            filters={filters}
            sort={carrierSort as Parameters<typeof CarrierLaneTable>[0]["sort"]}
            page={carrierPage}
            pageSize={50}
            onSortChange={(s) => updateUrl({ car_sort: s, car_page: null })}
            onPageChange={(p) => updateUrl({ car_page: p === 1 ? null : String(p) })}
          />
          <DetailsTable
            filters={filters}
            sort={detailsSort as Parameters<typeof DetailsTable>[0]["sort"]}
            page={detailsPage}
            pageSize={100}
            onSortChange={(s) => updateUrl({ det_sort: s, det_page: null })}
            onPageChange={(p) => updateUrl({ det_page: p === 1 ? null : String(p) })}
          />
        </div>
      </div>
    </div>
  )
}

function KpiCard({
  icon,
  label,
  value,
  sub,
  warn = false,
}: {
  icon?: React.ReactNode
  label: string
  value: string
  sub?: string
  warn?: boolean
}) {
  return (
    <div
      className={`rounded-xl border p-3 shadow-sm ${
        warn ? "border-[#FCD34D] bg-[#FFFBEB]" : "border-[#E5E7EB] bg-white"
      }`}
    >
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-[#6B7280]">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-[#1B3A5C]">
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-[#6B7280]">{sub}</div>}
    </div>
  )
}

export default function CarrierRiskPage() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["carrier-risk"]]}>
      <Suspense
        fallback={
          <div className="flex h-[60vh] items-center justify-center text-[#6B7280]">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        }
      >
        <CarrierRiskContent />
      </Suspense>
    </RoleGuard>
  )
}
