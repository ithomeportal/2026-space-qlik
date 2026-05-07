"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { ArrowLeft, Activity, Loader2 } from "lucide-react"
import {
  XrayDfwApiProvider,
  useXrayDfwFilters,
  type XrayDfwFilters,
  type XrayDfwRange,
} from "@/lib/xray-dfw-api"
import { Overview } from "@/app/reports/xray-dfw-mng/tabs/Overview"
import { CustomersLanes } from "@/app/reports/xray-dfw-mng/tabs/CustomersLanes"
import { Teams } from "@/app/reports/xray-dfw-mng/tabs/Teams"
import { Trends } from "@/app/reports/xray-dfw-mng/tabs/Trends"
import { Risk } from "@/app/reports/xray-dfw-mng/tabs/Risk"
import { ContractSpot } from "@/app/reports/xray-dfw-mng/tabs/ContractSpot"

const YEAR_START = "2026-01-01"
const YEAR_END = "2026-12-31"

type TabKey = "overview" | "customers" | "teams" | "trends" | "risk" | "contract-spot"

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "customers", label: "Customers & Lanes" },
  { key: "teams", label: "Teams" },
  { key: "trends", label: "Trends" },
  { key: "risk", label: "Risk" },
  { key: "contract-spot", label: "Contract vs Spot" },
]

const ALL_SUB_TEAMS = ["TM1", "TM2", "TM3", "TM4"]

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

interface Props {
  apiPrefix: string
  title: string
  /** When set, hides the team-pill row and forces the filter to that single TM. */
  lockedTeam?: "TM1" | "TM2" | "TM3" | "TM4"
}

/**
 * Shared content for the XRay DFW Mng report and its 4 per-team siblings.
 * The `apiPrefix` flows through `XrayDfwApiProvider` so every hook below
 * automatically points at the right backend router. `lockedTeam` swaps the
 * sub-team pill row for a static badge.
 */
export function XrayDfwReportContent({ apiPrefix, title, lockedTeam }: Props) {
  return (
    <XrayDfwApiProvider prefix={apiPrefix}>
      <Body title={title} lockedTeam={lockedTeam} />
    </XrayDfwApiProvider>
  )
}

function Body({ title, lockedTeam }: { title: string; lockedTeam?: Props["lockedTeam"] }) {
  const [activeTab, setActiveTab] = useState<TabKey>("overview")
  const [range, setRange] = useState<XrayDfwRange>("mtd")
  const [startDate, setStartDate] = useState<string>(YEAR_START)
  const [endDate, setEndDate] = useState<string>(clampToYear(todayIso()))
  const [subTeams, setSubTeams] = useState<string[]>([])
  const [customerInput, setCustomerInput] = useState<string>("")
  const [customer, setCustomer] = useState<string>("")

  const { data: filterRes, isLoading: loadingFilters } = useXrayDfwFilters()
  const filterOptions = filterRes?.data

  const appliedDates = useMemo(() => {
    if (range === "full") return { startDate: YEAR_START, endDate: YEAR_END }
    if (range === "ytd") return { startDate: YEAR_START, endDate: clampToYear(todayIso()) }
    if (range === "mtd") return { startDate: monthStartIso(), endDate: clampToYear(todayIso()) }
    return { startDate: clampToYear(startDate), endDate: clampToYear(endDate) }
  }, [range, startDate, endDate])

  // When a TM is locked we ignore subTeams state entirely. Backend already
  // hard-locks the team (defense in depth), but we omit the param to keep
  // the URL clean.
  const effectiveSubTeams = lockedTeam ? undefined : subTeams.length ? subTeams : undefined

  const filters: XrayDfwFilters = useMemo(
    () => ({
      range,
      startDate: appliedDates.startDate,
      endDate: appliedDates.endDate,
      subTeams: effectiveSubTeams,
      customer: customer || undefined,
    }),
    [range, appliedDates, effectiveSubTeams, customer],
  )

  const customerSuggestions = useMemo(() => {
    const q = customerInput.trim().toLowerCase()
    if (!q || !filterOptions?.customers) return []
    return filterOptions.customers.filter((c) => c.toLowerCase().includes(q)).slice(0, 8)
  }, [customerInput, filterOptions])

  const toggleSubTeam = (t: string) => {
    setSubTeams((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }

  const teamSummary = lockedTeam
    ? lockedTeam
    : subTeams.length
      ? subTeams.join(", ")
      : "All"

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link href="/" className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]">
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-[#2563EB]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">{title}</h1>
          <span className="rounded-full bg-[#F3F4F6] px-2 py-0.5 text-xs text-[#6B7280]">Management</span>
        </div>
        <div className="ml-auto text-xs text-[#6B7280]">
          {appliedDates.startDate} → {appliedDates.endDate}
          {" · "}
          Team: {teamSummary}
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

          {lockedTeam ? (
            <div className="flex items-center gap-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">Team</label>
              <span className="rounded-full border border-[#1B3A5C] bg-[#1B3A5C] px-3 py-1 text-xs text-white">
                {lockedTeam}
              </span>
              <span className="text-[10px] text-[#6B7280]">(locked)</span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">Team</label>
              <div className="flex flex-wrap gap-1">
                <button
                  onClick={() => setSubTeams([])}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    subTeams.length === 0
                      ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                      : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                  }`}
                >
                  All
                </button>
                {(filterOptions?.sub_teams ?? ALL_SUB_TEAMS).map((t) => (
                  <button
                    key={t}
                    onClick={() => toggleSubTeam(t)}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      subTeams.includes(t)
                        ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                        : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
          )}

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
                  ? "border-[#1B3A5C] text-[#1B3A5C]"
                  : "border-transparent text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1920px] flex-1 px-6 py-6">
        {activeTab === "overview" && <Overview filters={filters} />}
        {activeTab === "customers" && <CustomersLanes filters={filters} />}
        {activeTab === "teams" && <Teams filters={filters} />}
        {activeTab === "trends" && <Trends filters={filters} />}
        {activeTab === "risk" && <Risk filters={filters} />}
        {activeTab === "contract-spot" && <ContractSpot filters={filters} />}
      </div>
    </div>
  )
}
