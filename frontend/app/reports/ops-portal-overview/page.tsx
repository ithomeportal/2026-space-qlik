"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { ArrowLeft, LayoutGrid, Loader2 } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import {
  useOppActuals,
  useOppFilters,
  type LoadType,
  type OppFilters,
  type OppRange,
} from "@/lib/ops-portal-overview-api"
import { ComboChart } from "./Chart"
import { ServiceChart } from "./ServiceChart"
import { SidePanels } from "./SidePanels"
import { TeamLastMonthPerformance, TeamVariancePerformance } from "./TeamMonthDelta"
import { ProductionByCustomer } from "./ProductionByCustomer"
import { Actuals } from "./Actuals"
import { ActualsByLane } from "./ActualsByLane"
import { ByOrder } from "./ByOrder"

const YEAR_START = "2026-01-01"
const YEAR_END = "2026-12-31"

function pad(n: number) {
  return String(n).padStart(2, "0")
}
function iso(d: Date) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function todayIso() {
  return iso(new Date())
}
function monthStartIso() {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-01`
}
function monthEndIso() {
  const d = new Date()
  return iso(new Date(d.getFullYear(), d.getMonth() + 1, 0))
}
function lastMonthStartIso() {
  const d = new Date()
  return iso(new Date(d.getFullYear(), d.getMonth() - 1, 1)) // 1st of previous month
}
function lastMonthEndIso() {
  const d = new Date()
  return iso(new Date(d.getFullYear(), d.getMonth(), 0)) // day 0 of this month = last day of prev
}
function clampToYear(iso: string) {
  if (iso < YEAR_START) return YEAR_START
  if (iso > YEAR_END) return YEAR_END
  return iso
}

export default function OpsPortalOverviewPage() {
  return (
    <ReportGuard reportKey="ops-portal-overview">
      <OpsPortalOverviewContent />
    </ReportGuard>
  )
}

function OpsPortalOverviewContent() {
  // Default = current month (Bruno: "Date: dafault value (this month)")
  const [range, setRange] = useState<OppRange>("mtd")
  const [startDate, setStartDate] = useState<string>(monthStartIso())
  const [endDate, setEndDate] = useState<string>(clampToYear(todayIso()))
  const [team, setTeam] = useState<string>("")
  const [customerInput, setCustomerInput] = useState<string>("")
  const [customer, setCustomer] = useState<string>("")
  const [loadType, setLoadType] = useState<LoadType>("")
  // Bruno R5: "Losses" button — global toggle (margin_amt < 0) for the
  // Production by Customer / Actuals / By Lane / By Order tables.
  const [lossesOnly, setLossesOnly] = useState<boolean>(false)

  const { data: filterRes, isLoading: loadingFilters } = useOppFilters()
  const filterOptions = filterRes?.data

  const appliedDates = useMemo(() => {
    if (range === "ytd")        return { startDate: YEAR_START, endDate: clampToYear(todayIso()) }
    if (range === "mtd")        return { startDate: monthStartIso(), endDate: clampToYear(todayIso()) }
    if (range === "this_month") return { startDate: monthStartIso(), endDate: clampToYear(monthEndIso()) }
    if (range === "last_month") return { startDate: lastMonthStartIso(), endDate: lastMonthEndIso() }
    return { startDate: clampToYear(startDate), endDate: clampToYear(endDate) }
  }, [range, startDate, endDate])

  const filters: OppFilters = useMemo(
    () => ({
      range,
      startDate: appliedDates.startDate,
      endDate: appliedDates.endDate,
      team: team || undefined,
      customer: customer || undefined,
      loadType: loadType || undefined,
      lossesOnly: lossesOnly || undefined,
    }),
    [range, appliedDates, team, customer, loadType, lossesOnly],
  )

  const customerSuggestions = useMemo(() => {
    const q = customerInput.trim().toLowerCase()
    if (!q || !filterOptions?.customers) return []
    return filterOptions.customers.filter((c) => c.toLowerCase().includes(q)).slice(0, 8)
  }, [customerInput, filterOptions])

  // Bruno R4 (2026-05-27): "last auto-refresh" stamp. Shares the /actuals cache
  // key with the Actuals table, so this adds no extra fetch.
  const { dataUpdatedAt } = useOppActuals(filters, { sort: "revenue_desc", limit: 200 })
  const refreshedLabel =
    dataUpdatedAt > 0
      ? new Date(dataUpdatedAt).toLocaleString("en-US", {
          month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
        })
      : "—"

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Top bar */}
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link href="/" className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]">
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <div className="flex items-center gap-2">
          <LayoutGrid className="h-4 w-4 text-[#2563EB]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">Ops Portal - Overview</h1>
          <span className="rounded-full bg-[#F3F4F6] px-2 py-0.5 text-xs text-[#6B7280]">CORP</span>
        </div>
        <div className="ml-auto flex flex-col items-end text-xs text-[#6B7280]">
          <div>
            {appliedDates.startDate} → {appliedDates.endDate}
            {" · "}
            Team: {team || "All"}
            {" · "}
            Customer: {customer || "All"}
            {loadType && ` · ${loadType === "contract" ? "Contractual" : "Spot"}`}
          </div>
          <div className="text-[11px] text-[#9CA3AF]">
            Last auto-refreshed: <span className="font-medium text-[#6B7280]">{refreshedLabel}</span>
          </div>
        </div>
      </div>

      {/* Filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">Range</label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {[
                { k: "ytd" as const,        label: "YTD" },
                { k: "mtd" as const,        label: "MTD" },
                { k: "this_month" as const, label: "This Month" },
                { k: "last_month" as const, label: "Last Month" },
                { k: "custom" as const,     label: "Custom" },
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
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">Teams</label>
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
              {(filterOptions?.teams ?? []).map((t) => (
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

          {/* Bruno R5: Losses button — filters PdC / Actuals / By Lane / By Order to margin<0. */}
          <button
            onClick={() => setLossesOnly((v) => !v)}
            title="Show only loss-making records (margin < 0) in the Production by Customer, Actuals, By Lane and By Order tables"
            className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              lossesOnly
                ? "border-[#DC2626] bg-[#DC2626] text-white"
                : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
            }`}
          >
            Losses
          </button>

          {loadingFilters && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-4 px-6 py-4">
        {/* Bruno R5 #1: Service (OTP/OTD) chart is now the first chart. */}
        <ServiceChart filters={filters} loadType={loadType} />

        {/* Bruno R5 #5/#6/#7: the KPI MANAGEMENT container ends with its KPI
            cards; the freed space below it holds the two new month tables. */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.5fr_1fr]">
          <div className="space-y-4">
            <ComboChart filters={filters} loadType={loadType} setLoadType={setLoadType} />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <TeamLastMonthPerformance filters={filters} />
              <TeamVariancePerformance filters={filters} />
            </div>
          </div>
          <SidePanels filters={filters} />
        </div>

        <ProductionByCustomer filters={filters} />
        <Actuals filters={filters} />
        <ActualsByLane filters={filters} />
        <ByOrder filters={filters} />
      </div>
    </div>
  )
}
