"use client"

import { useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { ArrowLeft, Activity, Loader2 } from "lucide-react"
import {
  XrayDfwApiProvider,
  useXrayDfwFilters,
  type XrayDfwFilters,
  type XrayDfwRange,
  type XrayDfwView,
} from "@/lib/xray-dfw-api"
import { MultiSelectChips } from "@/components/MultiSelectChips"
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
  const [customers, setCustomers] = useState<string[]>([])
  const [lanes, setLanes] = useState<string[]>([])
  const [contractTypes, setContractTypes] = useState<string[]>([])
  const [equipment, setEquipment] = useState<string[]>([])
  // Bruno (2026-05-28): the RUAN pseudo-team. view="ruan" scopes to RUAN
  // customers under TEAM-DFW and swaps the entity from customer_name → client.
  const [view, setView] = useState<XrayDfwView | undefined>(undefined)

  const isRuan = view === "ruan"
  const entityLabel = isRuan ? "Client" : "Customer"

  const { data: filterRes, isLoading: loadingFilters } = useXrayDfwFilters(view)
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
      customers: customers.length ? customers : undefined,
      lanes: lanes.length ? lanes : undefined,
      contractTypes: contractTypes.length ? contractTypes : undefined,
      equipment: equipment.length ? equipment : undefined,
      view,
    }),
    [range, appliedDates, effectiveSubTeams, customers, lanes, contractTypes, equipment, view],
  )

  // Toggling any normal team selection exits the RUAN view and clears the
  // customer filter (a client value can't match a customer_name).
  const exitRuanIfNeeded = useCallback(() => {
    if (isRuan) {
      setView(undefined)
      setCustomers([])
    }
  }, [isRuan])

  const selectAllTeams = () => {
    exitRuanIfNeeded()
    setSubTeams([])
  }

  const toggleSubTeam = (t: string) => {
    exitRuanIfNeeded()
    setSubTeams((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }

  const selectRuan = () => {
    // RUAN forces TEAM-DFW scope server-side; clear teams/customers/lanes so the
    // view is unambiguous and a stale customer_name doesn't leak in.
    setView("ruan")
    setSubTeams([])
    setCustomers([])
    setLanes([])
  }

  const onCustomerClick = useCallback((name: string) => {
    if (!name) return
    setCustomers((prev) => (prev.includes(name) ? prev : [...prev, name]))
  }, [])

  const onLaneClick = useCallback((lane: string) => {
    if (!lane) return
    setLanes((prev) => (prev.includes(lane) ? prev : [...prev, lane]))
  }, [])

  const teamSummary = lockedTeam
    ? lockedTeam
    : isRuan
      ? "RUAN (DFW)"
      : subTeams.length
        ? subTeams.join(", ")
        : "All"

  const entitySummary = customers.length
    ? customers.length === 1
      ? customers[0]
      : `${customers.length} ${entityLabel.toLowerCase()}s`
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
          {entityLabel}: {entitySummary}
          {lanes.length > 0 && ` · Lanes: ${lanes.length}`}
          {contractTypes.length > 0 && ` · Contract/Spot: ${contractTypes.length}`}
          {equipment.length > 0 && ` · Equipment: ${equipment.length}`}
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
                  onClick={selectAllTeams}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    !isRuan && subTeams.length === 0
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
                      !isRuan && subTeams.includes(t)
                        ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                        : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                    }`}
                  >
                    {t}
                  </button>
                ))}
                <button
                  onClick={selectRuan}
                  title="RUAN — TEAM-DFW RUAN customers, broken down by client"
                  className={`rounded-full border px-3 py-1 text-xs font-semibold transition-colors ${
                    isRuan
                      ? "border-[#7C3AED] bg-[#7C3AED] text-white"
                      : "border-[#DDD6FE] bg-[#F5F3FF] text-[#6D28D9] hover:bg-[#EDE9FE]"
                  }`}
                >
                  RUAN
                </button>
              </div>
            </div>
          )}

          <MultiSelectChips
            label={entityLabel}
            options={filterOptions?.customers ?? []}
            selected={customers}
            onChange={setCustomers}
            placeholder={loadingFilters ? "Loading…" : `All ${entityLabel.toLowerCase()}s`}
            width={240}
          />

          <MultiSelectChips
            label="Lane"
            options={filterOptions?.lanes ?? []}
            selected={lanes}
            onChange={setLanes}
            placeholder={loadingFilters ? "Loading…" : "All lanes"}
            width={260}
          />

          <MultiSelectChips
            label="Contract/Spot"
            options={filterOptions?.contract_types ?? []}
            selected={contractTypes}
            onChange={setContractTypes}
            placeholder={loadingFilters ? "Loading…" : "All types"}
            width={200}
          />

          <MultiSelectChips
            label="Equipment"
            options={filterOptions?.equipment_groups ?? []}
            selected={equipment}
            onChange={setEquipment}
            placeholder={loadingFilters ? "Loading…" : "All equipment"}
            width={220}
          />

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
        {activeTab === "overview" && <Overview filters={filters} entityLabel={entityLabel} />}
        {activeTab === "customers" && (
          <CustomersLanes
            filters={filters}
            entityLabel={entityLabel}
            onCustomerClick={onCustomerClick}
            onLaneClick={onLaneClick}
          />
        )}
        {activeTab === "teams" && <Teams filters={filters} />}
        {activeTab === "trends" && <Trends filters={filters} />}
        {activeTab === "risk" && (
          <Risk
            filters={filters}
            entityLabel={entityLabel}
            onCustomerClick={onCustomerClick}
            onLaneClick={onLaneClick}
          />
        )}
        {activeTab === "contract-spot" && (
          <ContractSpot
            filters={filters}
            entityLabel={entityLabel}
            onCustomerClick={onCustomerClick}
            onLaneClick={onLaneClick}
          />
        )}
      </div>
    </div>
  )
}
