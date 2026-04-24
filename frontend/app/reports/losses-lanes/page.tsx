"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import {
  ArrowLeft,
  DollarSign,
  Loader2,
  Percent,
  TrendingDown,
  Truck,
} from "lucide-react"
import {
  useLossesFilters,
  useLossesSummary,
  type LossesFilters,
  type LossesRange,
} from "@/lib/losses-lanes-api"
import { LossesErrorBanner } from "./ErrorBanner"
import { WorstLanes } from "./tabs/WorstLanes"
import { WorstCustomers } from "./tabs/WorstCustomers"
import { TopCombo } from "./tabs/TopCombo"
import { Trends } from "./tabs/Trends"
import { OrderDetails } from "./tabs/OrderDetails"

const YEAR_START = "2026-01-01"
const YEAR_END = "2026-12-31"

const ALL_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW"] as const

type TabKey = "lanes" | "customers" | "top" | "trends" | "orders"

const TABS: { key: TabKey; label: string }[] = [
  { key: "lanes", label: "Worst Margins by Lane" },
  { key: "customers", label: "Worst Margins by Customer" },
  { key: "top", label: "Top 10 Combo" },
  { key: "trends", label: "Trends" },
  { key: "orders", label: "Order Details" },
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

const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const COUNT = new Intl.NumberFormat("en-US")
const PCT2 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
})

const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))
const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT.format(Number(v))
const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT2.format(Number(v))}%`

export default function LossesLanesPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("lanes")
  const [range, setRange] = useState<LossesRange>("mtd")
  const [startDate, setStartDate] = useState<string>(monthStartIso())
  const [endDate, setEndDate] = useState<string>(clampToYear(todayIso()))
  const [teams, setTeams] = useState<string[]>([...ALL_TEAMS])
  const [customerInput, setCustomerInput] = useState<string>("")
  const [customer, setCustomer] = useState<string>("")
  const [orderLane, setOrderLane] = useState<string | undefined>(undefined)

  const { data: filterRes, isLoading: loadingFilters } = useLossesFilters()
  const filterOptions = filterRes?.data

  const filters: LossesFilters = useMemo(
    () => ({
      range,
      startDate: range === "custom" ? clampToYear(startDate) : undefined,
      endDate: range === "custom" ? clampToYear(endDate) : undefined,
      teams,
      customer: customer || undefined,
    }),
    [range, startDate, endDate, teams, customer],
  )

  const { data: summaryRes, isLoading: loadingSummary, error: summaryErr } =
    useLossesSummary(filters)
  const s = summaryRes?.data

  const customerSuggestions = useMemo(() => {
    const q = customerInput.trim().toLowerCase()
    if (!q || !filterOptions?.customers) return []
    return filterOptions.customers.filter((c) => c.toLowerCase().includes(q)).slice(0, 8)
  }, [customerInput, filterOptions])

  const toggleTeam = (t: string) => {
    setTeams((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }

  const allTeamsSelected = teams.length === ALL_TEAMS.length
  const windowLabel = s?.window
    ? `${s.window.start} → ${s.window.end}`
    : range === "custom"
      ? `${clampToYear(startDate)} → ${clampToYear(endDate)}`
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
          <TrendingDown className="h-4 w-4 text-[#DC2626]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">Top Losses Lanes</h1>
          <span className="rounded-full bg-[#FEE2E2] px-2 py-0.5 text-xs text-[#991B1B]">
            margin &lt; 0
          </span>
        </div>
        <div className="ml-auto text-xs text-[#6B7280]">
          {windowLabel}
          {" · "}
          Teams: {allTeamsSelected ? "All" : teams.join(", ") || "None"}
          {" · "}
          Customer: {customer || "All"}
        </div>
      </div>

      {/* Filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
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

          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Teams
            </label>
            <button
              onClick={() =>
                setTeams(allTeamsSelected ? [] : [...ALL_TEAMS])
              }
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                allTeamsSelected
                  ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                  : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
              }`}
            >
              All
            </button>
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

        {/* Tab switcher */}
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

      {/* KPI cards */}
      <div className="mx-auto w-full max-w-[1920px] px-6 pt-4">
        <LossesErrorBanner errors={[summaryErr]} label="Summary" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <KpiCard
            icon={<Truck className="h-4 w-4" />}
            label="# Loads"
            value={loadingSummary ? "—" : fmtCount(s?.loads)}
            accent="text-[#DC2626]"
          />
          <KpiCard
            icon={<DollarSign className="h-4 w-4" />}
            label="Revenue"
            value={loadingSummary ? "—" : fmtUsd(s?.revenue)}
            accent="text-[#1B3A5C]"
          />
          <KpiCard
            icon={<TrendingDown className="h-4 w-4" />}
            label="$ Profit"
            value={loadingSummary ? "—" : fmtUsd(s?.profit)}
            accent="text-[#B45309]"
          />
          <KpiCard
            icon={<Percent className="h-4 w-4" />}
            label="% Margin"
            value={loadingSummary ? "—" : fmtPct(s?.margin_pct)}
            accent="text-[#7C3AED]"
          />
        </div>
      </div>

      {/* Tab body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 px-6 py-6">
        {activeTab === "lanes" && (
          <WorstLanes
            filters={filters}
            onDrillLane={(lane) => {
              setOrderLane(lane)
              setActiveTab("orders")
            }}
          />
        )}
        {activeTab === "customers" && <WorstCustomers filters={filters} />}
        {activeTab === "top" && (
          <TopCombo
            filters={filters}
            onDrillLane={(lane) => {
              setOrderLane(lane)
              setActiveTab("orders")
            }}
          />
        )}
        {activeTab === "trends" && <Trends filters={filters} />}
        {activeTab === "orders" && (
          <OrderDetails
            filters={filters}
            lane={orderLane}
            onClearLane={() => setOrderLane(undefined)}
          />
        )}
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
