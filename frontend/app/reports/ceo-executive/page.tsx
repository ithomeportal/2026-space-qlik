"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { ArrowLeft, Crown, Loader2 } from "lucide-react"
import {
  useCeoFilters,
  type CeoDivision,
  type CeoFilters,
  type CeoRange,
} from "@/lib/ceo-api"
import { Overview } from "./tabs/Overview"
import { Trends } from "./tabs/Trends"
import { Customers } from "./tabs/Customers"
import { Weekly } from "./tabs/Weekly"
import { ReportGuard } from "@/components/ReportGuard"
import { Risk } from "./tabs/Risk"
import { Orders } from "./tabs/Orders"

const YEAR_START = "2026-01-01"
const YEAR_END = "2026-12-31"

// Fallback team lists used before /filters resolves, and to drop a team
// selection that is incompatible with the current division.
const CORP_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"] as const
const DFW_SUB_TEAMS = ["TM1", "TM2", "TM3", "TM4"] as const

// Overview now bundles Overview + Trends + Customers content, stacked in that
// order, so those two no longer get their own tabs.
type TabKey = "overview" | "weekly" | "risk" | "orders"

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "weekly", label: "Weekly" },
  { key: "risk", label: "Risk" },
  { key: "orders", label: "Orders" },
]

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
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

export default function CeoExecutivePage() {
  return (
    <ReportGuard reportKey="ceo-executive">
      <CeoExecutiveContent />
    </ReportGuard>
  )
}

function CeoExecutiveContent() {
  const [activeTab, setActiveTab] = useState<TabKey>("overview")
  const [range, setRange] = useState<CeoRange>("mtd")
  const [startDate, setStartDate] = useState<string>(YEAR_START)
  const [endDate, setEndDate] = useState<string>(clampToYear(todayIso()))
  const [division, setDivision] = useState<CeoDivision | "">("") // "" = all
  const [team, setTeam] = useState<string>("") // "" = all
  const [customerInput, setCustomerInput] = useState<string>("")
  const [customer, setCustomer] = useState<string>("")

  const { data: filterRes, isLoading: loadingFilters } = useCeoFilters()
  const filterOptions = filterRes?.data

  // Team pill list narrows with the selected division. Fall back to the
  // hard-coded constants so the UI stays usable if /filters is still loading.
  const teamOptions = useMemo<string[]>(() => {
    const byDiv = filterOptions?.teams_by_division
    if (division === "CORP") return byDiv?.CORP ?? [...CORP_TEAMS]
    if (division === "DFW") return byDiv?.DFW ?? [...DFW_SUB_TEAMS]
    return filterOptions?.teams ?? [...CORP_TEAMS, ...DFW_SUB_TEAMS]
  }, [division, filterOptions])

  // Drop a team selection that is incompatible with the new division.
  function selectDivision(next: CeoDivision | "") {
    setDivision(next)
    if (!team) return
    if (next === "CORP" && !CORP_TEAMS.includes(team as (typeof CORP_TEAMS)[number])) {
      setTeam("")
    } else if (
      next === "DFW" &&
      !DFW_SUB_TEAMS.includes(team as (typeof DFW_SUB_TEAMS)[number])
    ) {
      setTeam("")
    }
  }

  const appliedDates = useMemo(() => {
    if (range === "full") return { startDate: YEAR_START, endDate: YEAR_END }
    if (range === "ytd")
      return { startDate: YEAR_START, endDate: clampToYear(todayIso()) }
    if (range === "mtd")
      return { startDate: monthStartIso(), endDate: clampToYear(todayIso()) }
    return { startDate: clampToYear(startDate), endDate: clampToYear(endDate) }
  }, [range, startDate, endDate])

  const filters: CeoFilters = useMemo(
    () => ({
      range,
      startDate: appliedDates.startDate,
      endDate: appliedDates.endDate,
      division: division || undefined,
      team: team || undefined,
      customer: customer || undefined,
    }),
    [range, appliedDates, division, team, customer],
  )

  const customerSuggestions = useMemo(() => {
    const q = customerInput.trim().toLowerCase()
    if (!q || !filterOptions?.customers) return []
    return filterOptions.customers.filter((c) => c.toLowerCase().includes(q)).slice(0, 8)
  }, [customerInput, filterOptions])

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link href="/" className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]">
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <div className="flex items-center gap-2">
          <Crown className="h-4 w-4 text-[#D97706]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">CEO Executive</h1>
          <span className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-xs text-[#92400E]">Executive</span>
        </div>
        <div className="ml-auto text-xs text-[#6B7280]">
          {appliedDates.startDate} → {appliedDates.endDate}
          {" · "}
          Division: {division || "All"}
          {" · "}
          Team: {team || "All"}
          {" · "}
          Customer: {customer || "All"}
        </div>
      </div>

      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">Range</label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {[
                { k: "mtd" as const, label: "MTD" },
                { k: "ytd" as const, label: "YTD" },
                { k: "full" as const, label: "Full 2026" },
                { k: "custom" as const, label: "Custom" },
              ].map((opt) => (
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
                  min={YEAR_START}
                  max={YEAR_END}
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
                <span className="text-[#6B7280]">→</span>
                <input
                  type="date"
                  min={YEAR_START}
                  max={YEAR_END}
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">Division</label>
            <div className="flex flex-wrap gap-1">
              {[
                { k: "" as const, label: "All" },
                { k: "CORP" as const, label: "CORP" },
                { k: "DFW" as const, label: "DFW" },
              ].map((opt) => (
                <button
                  key={opt.label}
                  onClick={() => selectDivision(opt.k)}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    division === opt.k
                      ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                      : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">Team</label>
            <div className="flex flex-wrap gap-1">
              <button
                onClick={() => setTeam("")}
                className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                  team === ""
                    ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                    : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                }`}
              >
                All
              </button>
              {teamOptions.map((t) => (
                <button
                  key={t}
                  onClick={() => setTeam(t)}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    team === t
                      ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                      : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div className="relative flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">Customer</label>
            <input
              type="text"
              placeholder={loadingFilters ? "Loading…" : customer || "All customers"}
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

          {loadingFilters && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
        </div>

        <div className="mx-auto flex w-full max-w-[1920px] gap-1 overflow-x-auto border-t border-[#E5E7EB] px-6">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`border-b-2 px-4 py-2 text-xs font-semibold transition-colors ${
                activeTab === tab.key
                  ? "border-[#D97706] text-[#D97706]"
                  : "border-transparent text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1920px] flex-1 px-6 py-6">
        {activeTab === "overview" && (
          <div className="space-y-10">
            <Overview filters={filters} />
            <Trends filters={filters} />
            <Customers filters={filters} />
          </div>
        )}
        {activeTab === "weekly" && <Weekly filters={filters} />}
        {activeTab === "risk" && <Risk filters={filters} />}
        {activeTab === "orders" && <Orders filters={filters} />}
      </div>
    </div>
  )
}
