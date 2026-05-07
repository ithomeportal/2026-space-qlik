"use client"

import { Suspense, useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Loader2, Users } from "lucide-react"
import {
  useAttritionFilters,
  useAttritionFreshness,
  type AttritionFilters,
} from "@/lib/attrition-wow-api"
import { fmtTimestamp, fmtWeekRange } from "./format"
import { OverviewTab } from "./tabs/OverviewTab"
import { ReactiveTab } from "./tabs/ReactiveTab"
import { PivotsTab } from "./tabs/PivotsTab"
import { TrendsTab } from "./tabs/TrendsTab"
import { ReportGuard } from "@/components/ReportGuard"
const ALL_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW"] as const
const CORP_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"]
const DFW_TEAMS = ["TEAM-DFW"]

type TabKey = "overview" | "reactive" | "pivots"

// Bruno (2026-04-27): merged "12-Week Pivots" + "Weekly Trends" into one tab.
const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "reactive", label: "Reactive Customers" },
  { key: "pivots", label: "Trends & Pivots" },
]

function AttritionContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  const rawTab = searchParams.get("tab")
  // Migration: legacy ?tab=trends links land on the merged Pivots tab.
  const activeTab: TabKey =
    rawTab === "reactive" || rawTab === "pivots"
      ? rawTab
      : rawTab === "trends"
        ? "pivots"
        : "overview"
  const teamsParam = searchParams.get("teams")
  const teams = useMemo<string[]>(() => {
    if (teamsParam === null) return [...ALL_TEAMS]
    if (teamsParam === "") return []
    return teamsParam
      .split(",")
      .filter((t) => (ALL_TEAMS as readonly string[]).includes(t))
  }, [teamsParam])
  const customer = searchParams.get("customer") || ""
  const contract = searchParams.get("contract") || ""
  const lane = searchParams.get("lane") || ""

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

  const setTab = (tab: TabKey) =>
    updateUrl({ tab: tab === "overview" ? null : tab })
  const setCustomer = (c: string) => updateUrl({ customer: c || null })
  const setContract = (c: string) => updateUrl({ contract: c || null })
  const setLane = (l: string) => updateUrl({ lane: l || null })
  const setTeams = (next: string[]) => {
    if (next.length === ALL_TEAMS.length) updateUrl({ teams: null })
    else updateUrl({ teams: next.join(",") })
  }

  const toggleTeam = (t: string) => {
    setTeams(teams.includes(t) ? teams.filter((x) => x !== t) : [...teams, t])
  }
  const allTeamsSelected = teams.length === ALL_TEAMS.length
  const onlyCorp =
    teams.length === CORP_TEAMS.length &&
    teams.every((t) => CORP_TEAMS.includes(t))
  const onlyDfw =
    teams.length === DFW_TEAMS.length &&
    teams.every((t) => DFW_TEAMS.includes(t))

  const { data: filterRes, isLoading: loadingFilters } = useAttritionFilters()
  const filterOptions = filterRes?.data
  const { data: freshnessRes } = useAttritionFreshness()
  const fr = freshnessRes?.data

  const filters: AttritionFilters = useMemo(
    () => ({
      teams,
      customer: customer || undefined,
      contract: contract || undefined,
      lane: lane || undefined,
    }),
    [teams, customer, contract, lane],
  )

  const [customerInput, setCustomerInput] = useState<string>("")
  const customerSuggestions = useMemo(() => {
    const q = customerInput.trim().toLowerCase()
    if (!q || !filterOptions?.customers) return []
    return filterOptions.customers
      .filter((c) => c.toLowerCase().includes(q))
      .slice(0, 8)
  }, [customerInput, filterOptions])

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Mobile gate — Attrition WoW is desktop-only for now (dense pivots) */}
      <div className="border-b border-[#FDE68A] bg-[#FEF3C7] px-4 py-2 text-xs text-[#92400E] xl:hidden">
        <strong>Best viewed on desktop.</strong> Attrition WoW packs dense
        pivot tables and 15-week trend bars; mobile rendering is limited.
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
          <Users className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">Attrition WoW</h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-[10px] text-[#1E40AF]">
            week-over-week
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          {fr?.last_completed_week && (
            <span>
              Last week:{" "}
              {fmtWeekRange(
                fr.last_completed_week.start,
                fr.last_completed_week.end,
              )}
              {" · "}
              Teams:{" "}
              {allTeamsSelected ? "All" : teams.join(", ") || "None"}
              {customer ? ` · Customer: ${customer}` : ""}
              {contract ? ` · Contract: ${contract}` : ""}
              {lane ? ` · Lane: ${lane}` : ""}
            </span>
          )}
          {fr?.last_load_date && (
            <span
              className="rounded-full bg-[#F3F4F6] px-2 py-0.5 text-[10px] text-[#374151]"
              title={`Source: mcleod_gld_budget_report_v4 · ${fr.rows_in_scope.toLocaleString()} rows in scope`}
            >
              Data through: {fmtTimestamp(fr.last_load_date)}
            </span>
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Teams
            </label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              <TeamModeBtn
                label="All"
                active={allTeamsSelected}
                onClick={() => setTeams([...ALL_TEAMS])}
              />
              <TeamModeBtn
                label="CORP"
                active={onlyCorp}
                onClick={() => setTeams(CORP_TEAMS)}
              />
              <TeamModeBtn
                label="DFW"
                active={onlyDfw}
                onClick={() => setTeams(DFW_TEAMS)}
              />
            </div>
            <div className="flex flex-wrap gap-1">
              {ALL_TEAMS.map((t) => {
                const on = teams.includes(t)
                return (
                  <button
                    key={t}
                    onClick={() => toggleTeam(t)}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      on
                        ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                        : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                    }`}
                  >
                    {t}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="relative flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Customer
            </label>
            <input
              type="text"
              placeholder={
                loadingFilters ? "Loading…" : customer || "All customers"
              }
              value={customerInput}
              onChange={(e) => setCustomerInput(e.target.value)}
              onBlur={() => setTimeout(() => setCustomerInput(""), 150)}
              className="w-64 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            />
            {customerInput && customerSuggestions.length > 0 && (
              <ul className="absolute left-[calc(theme(spacing.2)+4.5rem)] top-full z-30 mt-1 max-h-64 w-64 overflow-auto rounded-md border border-[#E5E7EB] bg-white text-xs shadow-md">
                {customerSuggestions.map((c) => (
                  <li key={c}>
                    <button
                      onMouseDown={() => {
                        setCustomer(c)
                        setCustomerInput("")
                      }}
                      className="block w-full truncate px-3 py-1.5 text-left hover:bg-[#F3F4F6]"
                    >
                      {c}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {customer && (
              <button
                onClick={() => setCustomer("")}
                className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs text-[#6B7280] hover:bg-[#F3F4F6]"
              >
                Clear
              </button>
            )}
          </div>

          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Contract
            </label>
            <select
              value={contract}
              onChange={(e) => setContract(e.target.value)}
              className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            >
              <option value="">All</option>
              {filterOptions?.contract_types?.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          {lane && (
            <div className="flex items-center gap-2 rounded-full border border-[#E5E7EB] bg-[#F9FAFB] px-2 py-1 text-xs">
              <span className="text-[#6B7280]">Lane:</span>
              <span className="font-mono text-[#111827]">{lane}</span>
              <button
                onClick={() => setLane("")}
                className="text-[#6B7280] hover:text-[#111827]"
              >
                ×
              </button>
            </div>
          )}

          {loadingFilters && (
            <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />
          )}
        </div>

        {/* Tab switcher */}
        <div className="mx-auto flex w-full max-w-[1920px] gap-1 overflow-x-auto border-t border-[#E5E7EB] px-6">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setTab(tab.key)}
              className={`border-b-2 px-4 py-2 text-xs font-semibold transition-colors ${
                activeTab === tab.key
                  ? "border-[#1B3A5C] text-[#1B3A5C]"
                  : "border-transparent text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 px-6 py-6">
        {activeTab === "overview" && <OverviewTab filters={filters} />}
        {activeTab === "reactive" && <ReactiveTab filters={filters} />}
        {activeTab === "pivots" && (
          <div className="space-y-6">
            <PivotsTab filters={filters} />
            <TrendsTab filters={filters} />
          </div>
        )}
      </div>
    </div>
  )
}

function TeamModeBtn({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 ${
        active
          ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
          : "text-[#6B7280] hover:text-[#111827]"
      }`}
    >
      {label}
    </button>
  )
}

export default function AttritionWowPage() {
  return (
    <ReportGuard reportKey="attrition-wow">
      <Suspense
        fallback={
          <div className="flex min-h-[calc(100vh-64px)] items-center justify-center bg-[#F9FAFB]">
            <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
          </div>
        }
      >
        <AttritionContent />
      </Suspense>
    </ReportGuard>
  )
}
