"use client"

import { Suspense, useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import {
  ArrowLeft,
  Loader2,
  Receipt,
  Truck,
  X,
} from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import {
  useAdminCashflowFacets,
  useAdminCashflowKpis,
  useAdminCashflowSparklines,
  type AdminCashflowFilters,
  type AdminCashflowRange,
} from "@/lib/admin-cashflow-api"
import { KpiStrip } from "./KpiStrip"
import { AlarmBanner } from "./AlarmBanner"
import { UnbilledTables } from "./UnbilledTables"
import { AgingTabs } from "./AgingTabs"
import { AgingBucketsChart } from "./AgingBucketsChart"
import { TopDelayedCustomers } from "./TopDelayedCustomers"
import { fmtCount, fmtUsd } from "./format"

const ALL_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW"] as const
const ALL_COMPANIES = ["TMS", "TMS3"] as const

const RANGE_PRESETS: { k: AdminCashflowRange; label: string }[] = [
  { k: "today", label: "Today" },
  { k: "wtd", label: "WTD" },
  { k: "last_7d", label: "Last 7d" },
  { k: "mtd", label: "MTD" },
  { k: "last_month", label: "Last Month" },
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

function AdminCashflowContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  // ---- URL state -----------------------------------------------------------
  const range = (searchParams.get("range") as AdminCashflowRange) || "mtd"
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

  const companiesParam = searchParams.get("companies")
  const companies = useMemo<string[]>(() => {
    if (companiesParam === null) return [...ALL_COMPANIES]
    if (companiesParam === "") return []
    return companiesParam
      .split(",")
      .filter((c) => (ALL_COMPANIES as readonly string[]).includes(c))
  }, [companiesParam])

  const customer = searchParams.get("customer") || ""
  const contractType = searchParams.get("contract_type") || ""

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

  const setRange = (r: AdminCashflowRange) =>
    updateUrl({ range: r === "mtd" ? null : r })
  const setStartDate = (d: string) => updateUrl({ s: d })
  const setEndDate = (d: string) => updateUrl({ e: d })
  const setCustomer = (c: string) => updateUrl({ customer: c || null })
  const setContractType = (t: string) =>
    updateUrl({ contract_type: t || null })

  const setTeams = (next: string[]) => {
    if (next.length === ALL_TEAMS.length) updateUrl({ teams: null })
    else updateUrl({ teams: next.join(",") })
  }
  const toggleTeam = (t: string) => {
    setTeams(teams.includes(t) ? teams.filter((x) => x !== t) : [...teams, t])
  }

  const setCompanies = (next: string[]) => {
    if (next.length === ALL_COMPANIES.length) updateUrl({ companies: null })
    else updateUrl({ companies: next.join(",") })
  }
  const toggleCompany = (c: string) => {
    setCompanies(
      companies.includes(c) ? companies.filter((x) => x !== c) : [...companies, c],
    )
  }

  const filters: AdminCashflowFilters = useMemo(
    () => ({
      range,
      startDate: range === "custom" ? startDate : undefined,
      endDate: range === "custom" ? endDate : undefined,
      teams,
      companies,
      customer: customer || undefined,
      contractType: contractType || undefined,
    }),
    [range, startDate, endDate, teams, companies, customer, contractType],
  )

  // ---- Data ----------------------------------------------------------------
  const { data: facetsRes } = useAdminCashflowFacets()
  const facets = facetsRes?.data
  const { data: kpisRes, isLoading: loadingKpis } =
    useAdminCashflowKpis(filters)
  const k = kpisRes?.data
  const { data: sparkRes } = useAdminCashflowSparklines(filters)
  const spark = sparkRes?.data

  const [customerInput, setCustomerInput] = useState<string>("")
  const customerSuggestions = useMemo(() => {
    const q = customerInput.trim().toLowerCase()
    if (!q || !facets?.customers) return []
    return facets.customers
      .filter((c) => c.toLowerCase().includes(q))
      .slice(0, 8)
  }, [customerInput, facets])

  const allTeamsSelected = teams.length === ALL_TEAMS.length
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
          <Receipt className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">
            Admin Aging Cashflow
          </h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-[10px] text-[#1E40AF]">
            A/R discipline
          </span>
        </div>
        <div className="ml-auto text-xs text-[#6B7280]">
          {windowLabel}
          {" · "}
          Teams: {allTeamsSelected ? "All" : teams.join(", ") || "None"}
          {" · "}
          {customer ? `Customer: ${customer}` : "All customers"}
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

          {/* Companies */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Co.
            </label>
            <div className="flex flex-wrap gap-1">
              {ALL_COMPANIES.map((c) => {
                const active = companies.includes(c)
                return (
                  <button
                    key={c}
                    onClick={() => toggleCompany(c)}
                    className={`rounded-full px-2.5 py-1 text-xs ${
                      active
                        ? "bg-[#1B3A5C] text-white"
                        : "border border-[#E5E7EB] text-[#374151] hover:bg-[#F9FAFB]"
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

          {/* Contract Type */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Contract
            </label>
            <select
              value={contractType}
              onChange={(e) => setContractType(e.target.value)}
              className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
            >
              <option value="">All</option>
              {(facets?.contract_types ?? []).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] space-y-6 px-6 py-4">
        {/* Banner — visible only when total unbilled exceeds threshold */}
        {k?.alarm && (
          <AlarmBanner
            total={k.total_unbilled_usd}
            threshold={k.alarm_threshold_usd}
          />
        )}

        {/* KPI strip with sparklines */}
        <KpiStrip kpis={k} loading={loadingKpis} sparklines={spark} />

        {/* Aging buckets + Top delayed customers — side-by-side */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <AgingBucketsChart filters={filters} />
          </div>
          <div>
            <TopDelayedCustomers filters={filters} />
          </div>
        </div>

        {/* Two unbilled tables */}
        <UnbilledTables filters={filters} />

        {/* Aging detail tabs */}
        <AgingTabs filters={filters} />

        {/* Footer scope chips */}
        <div className="flex items-center gap-3 pb-6 text-[11px] text-[#6B7280]">
          <Truck className="h-3.5 w-3.5" />
          <span>Source: mcleod_gld_cashflow · Spark/McLeod ETL</span>
          <span>·</span>
          <span>Rows in scope: {fmtCount(k?.rows_in_scope)}</span>
          {k?.total_unbilled_usd !== undefined && (
            <>
              <span>·</span>
              <span>Total unbilled: {fmtUsd(k.total_unbilled_usd)}</span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default function AdminCashflowPage() {
  return (
    <ReportGuard reportKey="admin-cashflow">
      <Suspense
        fallback={
          <div className="flex h-[60vh] items-center justify-center text-[#6B7280]">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        }
      >
        <AdminCashflowContent />
      </Suspense>
    </ReportGuard>
  )
}
