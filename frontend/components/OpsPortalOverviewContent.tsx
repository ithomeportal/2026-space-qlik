"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { ArrowLeft, LayoutGrid, Loader2, RefreshCw } from "lucide-react"
import { useQueryClient } from "@tanstack/react-query"
import { MultiSelectChips, type FilterMode } from "@/components/MultiSelectChips"
import {
  OppApiProvider,
  useOppActuals,
  useOppFilters,
  type LoadType,
  type OppFilters,
  type OppRange,
} from "@/lib/ops-portal-overview-api"
import { ComboChart } from "@/app/reports/ops-portal-overview/Chart"
import { SidePanels } from "@/app/reports/ops-portal-overview/SidePanels"
import { ServiceIncidentTables } from "@/app/reports/ops-portal-overview/ServiceIncidentTables"
import { MarginDistribution } from "@/app/reports/ops-portal-overview/MarginDistribution"
import { Actuals } from "@/app/reports/ops-portal-overview/Actuals"
import { ActualsByLane } from "@/app/reports/ops-portal-overview/ActualsByLane"
import { ByOrder } from "@/app/reports/ops-portal-overview/ByOrder"

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

interface Props {
  /** Backend router prefix, e.g. "custom/ops-portal-overview-t1". Defaults to
   *  the cross-team router via the OppApiProvider default. */
  apiPrefix?: string
  /** Header title. */
  title?: string
  /** When set, hides the Teams pill row and locks the report to one CORP team
   *  (e.g. "TEAM1"). The backend router is also hard-locked — this is the UI
   *  half of the same lock. */
  lockedTeam?: string
  /** Header badge text (defaults to "CORP" / the locked team). */
  badge?: string
  /** Hides the "Bonus Calculator" quick-nav pill in the Go-to row. Set on the
   *  per-team CORP KAM portals so their KAMs don't reach the calculator from
   *  here (access is managed separately). */
  hideBonusNav?: boolean
}

/**
 * Shared content for the Ops Portal Overview report and its 4 per-team CORP
 * siblings (Bruno 2026-06-26). The `apiPrefix` flows through `OppApiProvider`
 * so every hook below automatically points at the right backend router.
 * `lockedTeam` swaps the Teams pill row for a static badge and pins the team
 * filter.
 */
export function OpsPortalOverviewContent({
  apiPrefix = "custom/ops-portal-overview",
  title = "OPS Managers Portal",
  lockedTeam,
  badge,
  hideBonusNav = false,
}: Props) {
  return (
    <OppApiProvider prefix={apiPrefix}>
      <Body title={title} lockedTeam={lockedTeam} badge={badge} hideBonusNav={hideBonusNav} />
    </OppApiProvider>
  )
}

function Body({
  title,
  lockedTeam,
  badge,
  hideBonusNav,
}: {
  title: string
  lockedTeam?: string
  badge?: string
  hideBonusNav?: boolean
}) {
  const qc = useQueryClient()
  // Default = current month (Bruno: "Date: dafault value (this month)")
  const [range, setRange] = useState<OppRange>("mtd")
  const [startDate, setStartDate] = useState<string>(monthStartIso())
  const [endDate, setEndDate] = useState<string>(clampToYear(todayIso()))
  // When a team is locked we never let `team` change; the cross-team report
  // starts at "" (All).
  const [team, setTeam] = useState<string>(lockedTeam ?? "")
  const [customerInput, setCustomerInput] = useState<string>("")
  const [customer, setCustomer] = useState<string>("")
  const [loadType, setLoadType] = useState<LoadType>("")
  // Bruno R5: "Losses" button — global toggle (margin_amt < 0) for the
  // Actuals / By Lane / By Order tables.
  const [lossesOnly, setLossesOnly] = useState<boolean>(false)
  // Bruno (PDF 2026-07-13): "Unbilled" button — bill_date < sentinel, same
  // three tables. ANDs with Losses when both are on.
  const [unbilledOnly, setUnbilledOnly] = useState<boolean>(false)
  // Bruno R7 (2026-06-05): Lane filter — multi-select with Include⇄Exclude.
  const [laneIds, setLaneIds] = useState<string[]>([])
  const [laneMode, setLaneMode] = useState<FilterMode>("include")
  // Bruno (PDF 2026-07-15) R1: Carrier filter — multi-select with Include⇄Exclude.
  const [carrierIds, setCarrierIds] = useState<string[]>([])
  const [carrierMode, setCarrierMode] = useState<FilterMode>("include")

  const { data: filterRes, isLoading: loadingFilters } = useOppFilters()
  const filterOptions = filterRes?.data

  // Defense in depth: even if some state mutated `team`, the locked report
  // always sends its own team (and the backend ignores any client team anyway).
  const effectiveTeam = lockedTeam ?? team

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
      team: effectiveTeam || undefined,
      customer: customer || undefined,
      loadType: loadType || undefined,
      lossesOnly: lossesOnly || undefined,
      unbilledOnly: unbilledOnly || undefined,
      lanes: laneMode === "include" && laneIds.length > 0 ? laneIds : undefined,
      excludeLanes: laneMode === "exclude" && laneIds.length > 0 ? laneIds : undefined,
      carriers: carrierMode === "include" && carrierIds.length > 0 ? carrierIds : undefined,
      excludeCarriers: carrierMode === "exclude" && carrierIds.length > 0 ? carrierIds : undefined,
    }),
    [range, appliedDates, effectiveTeam, customer, loadType, lossesOnly, unbilledOnly, laneIds, laneMode, carrierIds, carrierMode],
  )

  // R10: clicking a lane in the By-Lane table sets it as the single included lane.
  function pickLane(lane: string) {
    setLaneIds([lane])
    setLaneMode("include")
  }

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

  const headerBadge = badge ?? lockedTeam ?? "CORP"

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
          <h1 className="text-sm font-semibold text-[#1B3A5C]">{title}</h1>
          <span className="rounded-full bg-[#F3F4F6] px-2 py-0.5 text-xs text-[#6B7280]">{headerBadge}</span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          <div className="flex flex-col items-end">
            <div>
              {appliedDates.startDate} → {appliedDates.endDate}
              {" · "}
              Team: {effectiveTeam || "All"}
              {" · "}
              Customer: {customer || "All"}
              {laneIds.length > 0 &&
                ` · Lanes: ${laneMode === "exclude" ? "excl " : ""}${laneIds.length}`}
              {carrierIds.length > 0 &&
                ` · Carriers: ${carrierMode === "exclude" ? "excl " : ""}${carrierIds.length}`}
              {loadType && ` · ${loadType === "contract" ? "Contractual" : "Spot"}`}
            </div>
            <div className="text-[11px] text-[#9CA3AF]">
              Last auto-refreshed: <span className="font-medium text-[#6B7280]">{refreshedLabel}</span>
            </div>
          </div>
          <button
            onClick={() => qc.invalidateQueries()}
            title="Force refresh all data"
            className="flex items-center gap-1 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
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

          {/* Bruno R7 (2026-06-05): Lane filter — multi-select + Include⇄Exclude. */}
          <MultiSelectChips
            label="Lane"
            options={filterOptions?.lanes ?? []}
            selected={laneIds}
            onChange={setLaneIds}
            mode={laneMode}
            onModeChange={setLaneMode}
            placeholder={loadingFilters ? "Loading…" : "All lanes"}
            width={240}
          />

          {/* Bruno (PDF 2026-07-15) R1: Carrier filter — multi-select + Include⇄Exclude. */}
          <MultiSelectChips
            label="Carrier"
            options={filterOptions?.carriers ?? []}
            selected={carrierIds}
            onChange={setCarrierIds}
            mode={carrierMode}
            onModeChange={setCarrierMode}
            placeholder={loadingFilters ? "Loading…" : "All carriers"}
            width={220}
          />

          {/* Bruno (PDF 2026-07-15) R1: Contract Type filter — All / Contract / Spot.
              Wired to the same loadType the KPI Management chart toggles, so the
              two controls stay in sync and apply across every panel. */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Contract Type
            </label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {[
                { k: "" as LoadType,         label: "All" },
                { k: "contract" as LoadType, label: "Contract" },
                { k: "spot" as LoadType,     label: "Spot" },
              ].map((opt) => (
                <button
                  key={opt.k || "all"}
                  onClick={() => setLoadType(opt.k)}
                  className={`px-3 py-1.5 ${
                    loadType === opt.k
                      ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                      : "text-[#6B7280] hover:text-[#111827]"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Bruno R5: Losses button — filters Actuals / By Lane / By Order to margin<0. */}
          <button
            onClick={() => setLossesOnly((v) => !v)}
            title="Show only loss-making records (margin < 0) in the Actuals, By Lane and By Order tables"
            className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              lossesOnly
                ? "border-[#DC2626] bg-[#DC2626] text-white"
                : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
            }`}
          >
            Losses
          </button>

          {/* Bruno (PDF 2026-07-13): Unbilled button — bill_date < sentinel in the
              Actuals, By Lane and By Order tables. */}
          <button
            onClick={() => setUnbilledOnly((v) => !v)}
            title="Show only never-billed records (bill_date < '01-01-2000') in the Actuals, By Lane and By Order tables"
            className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              unbilledOnly
                ? "border-[#B45309] bg-[#B45309] text-white"
                : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
            }`}
          >
            Unbilled
          </button>

          {/* Bruno R1: quick-nav pills to sibling CORP reports. */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] uppercase tracking-wide text-[#9CA3AF]">Go to</span>
            {[
              { label: "Bonus Calculator", href: "/reports/bonus-calculator" },
              { label: "Ops Customer Score", href: "/reports/ops-customer-score" },
              { label: "Ops Margins", href: "/reports/ops-margins" },
              { label: "eSavings from Carriers", href: "/reports/esavings-carriers" },
              { label: "2026 Official Budget Follow Up", href: "/reports/budget-followup-2026" },
              { label: "Ops Direct Compare", href: "/reports/ops-direct-compare" },
              { label: "XRay CORP Mng", href: "/reports/xray-corp-mng" },
            ]
              // Per-team KAM portals hide the Bonus Calculator pill (access
              // managed separately); the main Ops Portal keeps it.
              .filter(({ href }) => !(hideBonusNav && href === "/reports/bonus-calculator"))
              .map(({ label, href }) => (
              <Link
                key={href}
                href={href}
                // Bruno (PDF 2026-07-15) R2: open the destination in a new tab.
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-full border border-[#E5E7EB] bg-white px-3 py-1 text-xs font-medium text-[#374151] hover:bg-[#F3F4F6] transition-colors whitespace-nowrap"
              >
                {label}
              </Link>
            ))}
          </div>

          {loadingFilters && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-4 px-6 py-4">
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.5fr_1fr]">
          <div className="space-y-4">
            <ComboChart filters={filters} loadType={loadType} setLoadType={setLoadType} />
            <ServiceIncidentTables filters={filters} onPickCustomer={setCustomer} />
          </div>
          <SidePanels filters={filters} onPickCustomer={setCustomer} lockedTeam={lockedTeam} />
        </div>

        <MarginDistribution filters={filters} />

        <Actuals filters={filters} onPickCustomer={setCustomer} />
        <ActualsByLane filters={filters} onPickLane={pickLane} />
        <ByOrder filters={filters} onPickCustomer={setCustomer} />
      </div>
    </div>
  )
}
