"use client"

import { Suspense, useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import {
  ArrowLeft,
  DollarSign,
  Loader2,
  Percent,
  TrendingDown,
  Truck,
} from "lucide-react"
import {
  useOpsFilters,
  useOpsFreshness,
  useOpsSummary,
  type OpsDivision,
  type OpsFilters,
  type OpsRange,
} from "@/lib/ops-margins-api"
import { OpsErrorBanner } from "./ErrorBanner"
import { fmtCount, fmtPct, fmtTimestamp, fmtUsd } from "./format"
import { Distribution } from "./tabs/Distribution"
import { LossesCombo } from "./tabs/LossesCombo"
import { MarginByCustomer } from "./tabs/MarginByCustomer"
import { MarginByLane } from "./tabs/MarginByLane"
import { NegativeCustomers } from "./tabs/NegativeCustomers"
import { NegativeOrders } from "./tabs/NegativeOrders"
import { Trend } from "./tabs/Trend"
import { WorstLanes } from "./tabs/WorstLanes"

const YEAR_START = "2026-01-01"
const YEAR_END = "2026-12-31"

const ALL_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW"] as const
const CORP_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"]
const DFW_TEAMS = ["TEAM-DFW"]
const DFW_SUB_TEAMS = ["TM1", "TM2", "TM3", "TM4"] as const
const ALL_COMPANIES = ["TMS", "TMS3"] as const

type TabKey =
  | "customers"
  | "lanes"
  | "worst"
  | "neg-orders"
  | "neg-customers"
  | "losses-combo"

const TABS: { key: TabKey; label: string }[] = [
  { key: "customers", label: "Margin by Customer" },
  { key: "lanes", label: "Margin by Lane" },
  { key: "worst", label: "Worst Margins by Lane" },
  { key: "neg-orders", label: "Negative Orders" },
  { key: "neg-customers", label: "Negative Customers" },
  { key: "losses-combo", label: "Losses by Month/Week" },
]

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

function OpsMarginsContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  // ---------- URL state ----------
  const activeTab = (searchParams.get("tab") as TabKey) || "customers"
  const range = (searchParams.get("range") as OpsRange) || "mtd"
  const startDate = searchParams.get("s") || monthStartIso()
  const endDate = searchParams.get("e") || clampToYear(todayIso())
  const divisionRaw = (searchParams.get("div") || "All") as OpsDivision
  const division: OpsDivision = ["All", "CORP", "DFW"].includes(divisionRaw)
    ? divisionRaw
    : "All"

  const teamsParam = searchParams.get("teams")
  const teams = useMemo<string[]>(() => {
    if (teamsParam === null) return [...ALL_TEAMS]
    if (teamsParam === "") return []
    return teamsParam
      .split(",")
      .filter((t) => (ALL_TEAMS as readonly string[]).includes(t))
  }, [teamsParam])

  const subTeamsParam = searchParams.get("sub")
  const subTeams = useMemo<string[]>(() => {
    if (!subTeamsParam) return []
    return subTeamsParam.split(",").filter((t) =>
      (DFW_SUB_TEAMS as readonly string[]).includes(t),
    )
  }, [subTeamsParam])

  const companiesParam = searchParams.get("co")
  const companies = useMemo<string[]>(() => {
    if (companiesParam === null) return [...ALL_COMPANIES]
    if (companiesParam === "") return []
    return companiesParam
      .split(",")
      .filter((c) => (ALL_COMPANIES as readonly string[]).includes(c))
  }, [companiesParam])

  const customer = searchParams.get("customer") || ""
  const origin = searchParams.get("origin") || ""
  const destination = searchParams.get("destination") || ""

  const t1Pct = Number(searchParams.get("t1") ?? "15")
  const t2Pct = Number(searchParams.get("t2") ?? "18")
  const t3Pct = Number(searchParams.get("t3") ?? "20")
  const thresholdsPct: [number, number, number] = [
    Number.isFinite(t1Pct) ? t1Pct : 15,
    Number.isFinite(t2Pct) ? t2Pct : 18,
    Number.isFinite(t3Pct) ? t3Pct : 20,
  ]

  // ---------- URL writers ----------
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

  const setTab = (tab: TabKey) =>
    updateUrl({ tab: tab === "customers" ? null : tab })
  const setRange = (r: OpsRange) => updateUrl({ range: r === "mtd" ? null : r })
  const setStartDate = (d: string) => updateUrl({ s: d })
  const setEndDate = (d: string) => updateUrl({ e: d })
  const setCustomer = (c: string) => updateUrl({ customer: c || null })
  const setOrigin = (o: string) => updateUrl({ origin: o || null })
  const setDestination = (d: string) => updateUrl({ destination: d || null })
  const setDivision = (d: OpsDivision) => {
    const patch: Record<string, string | null> = {
      div: d === "All" ? null : d,
      teams: null,
      sub: null,
    }
    updateUrl(patch)
  }
  const setTeams = (next: string[]) => {
    if (next.length === ALL_TEAMS.length) updateUrl({ teams: null })
    else updateUrl({ teams: next.join(",") })
  }
  const setSubTeams = (next: string[]) => {
    if (next.length === 0) updateUrl({ sub: null })
    else updateUrl({ sub: next.join(",") })
  }
  const setCompanies = (next: string[]) => {
    if (next.length === ALL_COMPANIES.length) updateUrl({ co: null })
    else updateUrl({ co: next.join(",") })
  }
  const setThresholdPct = (idx: 0 | 1 | 2, pct: number) => {
    const keys = ["t1", "t2", "t3"] as const
    const defaults = [15, 18, 20]
    updateUrl({
      [keys[idx]]:
        !Number.isFinite(pct) || pct === defaults[idx] ? null : String(pct),
    })
  }

  const allTeamsSelected = teams.length === ALL_TEAMS.length

  // ---------- Filters payload (for API hooks) ----------
  const filters: OpsFilters = useMemo(
    () => ({
      range,
      startDate: range === "custom" ? clampToYear(startDate) : undefined,
      endDate: range === "custom" ? clampToYear(endDate) : undefined,
      division,
      teams: allTeamsSelected ? undefined : teams,
      companies: companies.length === ALL_COMPANIES.length ? undefined : companies,
      subTeams: division === "DFW" && subTeams.length ? subTeams : undefined,
      customer: customer || undefined,
      origin: origin || undefined,
      destination: destination || undefined,
    }),
    [
      range,
      startDate,
      endDate,
      division,
      teams,
      allTeamsSelected,
      companies,
      subTeams,
      customer,
      origin,
      destination,
    ],
  )

  // ---------- Cascading filters lookup ----------
  const { data: filterRes, isLoading: loadingFilters } = useOpsFilters({
    division,
    teams: allTeamsSelected ? undefined : teams,
    companies: companies.length === ALL_COMPANIES.length ? undefined : companies,
    subTeams: division === "DFW" && subTeams.length ? subTeams : undefined,
    customer: customer || undefined,
    origin: origin || undefined,
  })
  const opts = filterRes?.data

  // ---------- Summary + freshness ----------
  const { data: summaryRes, isLoading: loadingSummary, error: summaryErr } =
    useOpsSummary(filters)
  const s = summaryRes?.data
  const { data: freshnessRes } = useOpsFreshness()
  const fr = freshnessRes?.data

  // ---------- Customer / origin / destination autosuggest ----------
  const [customerInput, setCustomerInput] = useState("")
  const [originInput, setOriginInput] = useState("")
  const [destInput, setDestInput] = useState("")

  const customerSuggestions = useMemo(() => {
    const q = customerInput.trim().toLowerCase()
    if (!q || !opts?.customers) return []
    return opts.customers.filter((c) => c.toLowerCase().includes(q)).slice(0, 8)
  }, [customerInput, opts])
  const originSuggestions = useMemo(() => {
    const q = originInput.trim().toLowerCase()
    if (!q || !opts?.origins) return []
    return opts.origins.filter((c) => c.toLowerCase().includes(q)).slice(0, 8)
  }, [originInput, opts])
  const destSuggestions = useMemo(() => {
    const q = destInput.trim().toLowerCase()
    if (!q || !opts?.destinations) return []
    return opts.destinations.filter((c) => c.toLowerCase().includes(q)).slice(0, 8)
  }, [destInput, opts])

  const windowLabel = s?.window
    ? `${s.window.start} → ${s.window.end}`
    : range === "custom"
      ? `${clampToYear(startDate)} → ${clampToYear(endDate)}`
      : range.replace("_", " ").toUpperCase()

  // Team chip list depends on division
  const teamChipList: readonly string[] =
    division === "CORP" ? CORP_TEAMS : division === "DFW" ? DFW_TEAMS : ALL_TEAMS
  const toggleTeam = (t: string) => {
    setTeams(teams.includes(t) ? teams.filter((x) => x !== t) : [...teams, t])
  }
  const toggleSubTeam = (st: string) => {
    setSubTeams(
      subTeams.includes(st) ? subTeams.filter((x) => x !== st) : [...subTeams, st],
    )
  }
  const toggleCompany = (c: string) => {
    setCompanies(
      companies.includes(c) ? companies.filter((x) => x !== c) : [...companies, c],
    )
  }

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Mobile gate — desktop-only (dense pivots, like Attrition WoW) */}
      <div className="border-b border-[#FDE68A] bg-[#FEF3C7] px-4 py-2 text-xs text-[#92400E] xl:hidden">
        <strong>Best viewed on desktop.</strong> OPs Margins shows wide tables and
        multi-column charts; mobile rendering is limited.
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
          <Percent className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">OPs Margins</h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-[10px] text-[#1E40AF]">
            best & worst
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          <span>
            {windowLabel} · Div: {division} · Teams:{" "}
            {allTeamsSelected ? "All" : teams.join(", ") || "None"}
            {customer ? ` · Customer: ${customer}` : ""}
          </span>
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

      {/* Filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          {/* Range */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Range
            </label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {[
                { k: "mtd" as const, label: "MTD" },
                { k: "last_month" as const, label: "Last Month" },
                { k: "ytd" as const, label: "This Year" },
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

          {/* Division */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Division
            </label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {(["All", "CORP", "DFW"] as const).map((d) => (
                <button
                  key={d}
                  onClick={() => setDivision(d)}
                  className={`px-3 py-1.5 ${
                    division === d
                      ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                      : "text-[#6B7280] hover:text-[#111827]"
                  }`}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>

          {/* Team chips */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Team
            </label>
            <div className="flex flex-wrap gap-1">
              {teamChipList.map((t) => {
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
            {division === "DFW" && (
              <div className="ml-2 flex items-center gap-1">
                <span className="text-[10px] uppercase tracking-wider text-[#6B7280]">
                  sub
                </span>
                {DFW_SUB_TEAMS.map((st) => {
                  const on = subTeams.includes(st)
                  return (
                    <button
                      key={st}
                      onClick={() => toggleSubTeam(st)}
                      className={`rounded-full border px-2 py-0.5 text-[10px] ${
                        on
                          ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                          : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                      }`}
                    >
                      {st}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* Company chips */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Company
            </label>
            <div className="flex flex-wrap gap-1">
              {ALL_COMPANIES.map((c) => {
                const on = companies.includes(c)
                return (
                  <button
                    key={c}
                    onClick={() => toggleCompany(c)}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      on
                        ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                        : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                    }`}
                  >
                    {c}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Customer */}
          <div className="relative flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Customer
            </label>
            <input
              type="text"
              placeholder={loadingFilters ? "Loading…" : customer || "All customers"}
              value={customerInput}
              onChange={(e) => setCustomerInput(e.target.value)}
              onBlur={() => setTimeout(() => setCustomerInput(""), 150)}
              className="w-56 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            />
            {customerInput && customerSuggestions.length > 0 && (
              <ul className="absolute left-[5rem] top-full z-30 mt-1 max-h-64 w-56 overflow-auto rounded-md border border-[#E5E7EB] bg-white text-xs shadow-md">
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

          {/* Origin */}
          <div className="relative flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Origin
            </label>
            <input
              type="text"
              placeholder={origin || "Any"}
              value={originInput}
              onChange={(e) => setOriginInput(e.target.value)}
              onBlur={() => setTimeout(() => setOriginInput(""), 150)}
              className="w-40 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            />
            {originInput && originSuggestions.length > 0 && (
              <ul className="absolute left-[4rem] top-full z-30 mt-1 max-h-64 w-48 overflow-auto rounded-md border border-[#E5E7EB] bg-white text-xs shadow-md">
                {originSuggestions.map((o) => (
                  <li key={o}>
                    <button
                      onMouseDown={() => {
                        setOrigin(o)
                        setOriginInput("")
                      }}
                      className="block w-full truncate px-3 py-1.5 text-left hover:bg-[#F3F4F6]"
                    >
                      {o}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {origin && (
              <button
                onClick={() => setOrigin("")}
                className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs text-[#6B7280] hover:bg-[#F3F4F6]"
              >
                Clear
              </button>
            )}
          </div>

          {/* Destination */}
          <div className="relative flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Destination
            </label>
            <input
              type="text"
              placeholder={destination || "Any"}
              value={destInput}
              onChange={(e) => setDestInput(e.target.value)}
              onBlur={() => setTimeout(() => setDestInput(""), 150)}
              className="w-40 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            />
            {destInput && destSuggestions.length > 0 && (
              <ul className="absolute left-[5.5rem] top-full z-30 mt-1 max-h-64 w-48 overflow-auto rounded-md border border-[#E5E7EB] bg-white text-xs shadow-md">
                {destSuggestions.map((o) => (
                  <li key={o}>
                    <button
                      onMouseDown={() => {
                        setDestination(o)
                        setDestInput("")
                      }}
                      className="block w-full truncate px-3 py-1.5 text-left hover:bg-[#F3F4F6]"
                    >
                      {o}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {destination && (
              <button
                onClick={() => setDestination("")}
                className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs text-[#6B7280] hover:bg-[#F3F4F6]"
              >
                Clear
              </button>
            )}
          </div>

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

      {/* KPI cards */}
      <div className="mx-auto w-full max-w-[1920px] px-6 pt-4">
        <OpsErrorBanner errors={[summaryErr]} label="Summary" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <KpiCard
            icon={<Percent className="h-4 w-4" />}
            label="Margin %"
            value={loadingSummary ? "—" : fmtPct(s?.margin_pct)}
            accent="text-[#7C3AED]"
          />
          <KpiCard
            icon={<Truck className="h-4 w-4" />}
            label="Loads"
            value={loadingSummary ? "—" : fmtCount(s?.loads)}
            accent="text-[#1B3A5C]"
          />
          <KpiCard
            icon={<TrendingDown className="h-4 w-4" />}
            label="Loss Loads"
            value={loadingSummary ? "—" : fmtCount(s?.loss_loads)}
            accent="text-[#DC2626]"
          />
          <KpiCard
            icon={<DollarSign className="h-4 w-4" />}
            label="Revenue"
            value={loadingSummary ? "—" : fmtUsd(s?.revenue)}
            accent="text-[#0F766E]"
          />
          <KpiCard
            icon={<DollarSign className="h-4 w-4" />}
            label="$ Profit"
            value={loadingSummary ? "—" : fmtUsd(s?.profit)}
            accent={
              (s?.profit ?? 0) >= 0 ? "text-[#15803D]" : "text-[#B91C1C]"
            }
          />
        </div>
      </div>

      {/* Trend + distribution (always shown above tabs) */}
      <div className="mx-auto grid w-full max-w-[1920px] grid-cols-1 gap-3 px-6 pt-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Trend filters={filters} />
        </div>
        <Distribution filters={filters} />
      </div>

      {/* Tab body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 px-6 py-6">
        {activeTab === "customers" && <MarginByCustomer filters={filters} />}
        {activeTab === "lanes" && <MarginByLane filters={filters} />}
        {activeTab === "worst" && (
          <WorstLanes
            filters={filters}
            thresholdsPct={thresholdsPct}
            onChangeThresholdPct={setThresholdPct}
          />
        )}
        {activeTab === "neg-orders" && <NegativeOrders filters={filters} />}
        {activeTab === "neg-customers" && <NegativeCustomers filters={filters} />}
        {activeTab === "losses-combo" && <LossesCombo filters={filters} />}
      </div>
    </div>
  )
}

function KpiCard({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode
  label: string
  value: string
  accent: string
}) {
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
          {label}
        </div>
        <div className={accent}>{icon}</div>
      </div>
      <div className={`mt-2 text-2xl font-semibold ${accent}`}>{value}</div>
    </div>
  )
}

export default function OpsMarginsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[calc(100vh-64px)] items-center justify-center bg-[#F9FAFB]">
          <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
        </div>
      }
    >
      <OpsMarginsContent />
    </Suspense>
  )
}
