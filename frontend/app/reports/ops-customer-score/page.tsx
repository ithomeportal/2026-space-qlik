"use client"

import { Suspense, useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Loader2 } from "lucide-react"
import {
  useOcsFilters,
  useOcsFreshness,
  type OcsDivision,
  type OcsFilters,
  type OcsRange,
} from "@/lib/ops-customer-score-api"
import { fmtCount, fmtTimestamp } from "./format"
import { PuOverview } from "./tabs/PuOverview"
import { DelOverview } from "./tabs/DelOverview"
import { Detail } from "./tabs/Detail"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"

const YEAR_START = "2026-01-01"
const YEAR_END = "2026-12-31"

const DFW_SUB_TEAMS = ["TM1", "TM2", "TM3", "TM4"] as const
const CORP_SUB_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"] as const
const ALL_COMPANIES = ["TMS", "TMS3"] as const

type TabKey = "pu-overview" | "del-overview" | "pu-detail" | "del-detail"

const TABS: { key: TabKey; label: string }[] = [
  { key: "pu-overview", label: "PU Overview" },
  { key: "del-overview", label: "DEL Overview" },
  { key: "pu-detail", label: "PU Detail" },
  { key: "del-detail", label: "DEL Detail" },
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

function OcsContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  const activeTab = (searchParams.get("tab") as TabKey) || "pu-overview"
  const range = (searchParams.get("range") as OcsRange) || "mtd"
  const startDate = searchParams.get("s") || monthStartIso()
  const endDate = searchParams.get("e") || clampToYear(todayIso())
  const divisionRaw = (searchParams.get("div") || "All") as OcsDivision
  const division: OcsDivision = ["All", "CORP", "DFW"].includes(divisionRaw)
    ? divisionRaw
    : "All"

  const subTeamsParam = searchParams.get("sub")
  const subTeams = useMemo<string[]>(() => {
    if (!subTeamsParam) return []
    return subTeamsParam.split(",").filter((t) =>
      (DFW_SUB_TEAMS as readonly string[]).includes(t),
    )
  }, [subTeamsParam])

  const corpTeamsParam = searchParams.get("corp")
  const corpTeams = useMemo<string[]>(() => {
    if (!corpTeamsParam) return []
    return corpTeamsParam.split(",").filter((t) =>
      (CORP_SUB_TEAMS as readonly string[]).includes(t),
    )
  }, [corpTeamsParam])

  const companiesParam = searchParams.get("co")
  const companies = useMemo<string[]>(() => {
    if (companiesParam === null) return [...ALL_COMPANIES]
    if (companiesParam === "") return []
    return companiesParam
      .split(",")
      .filter((c) => (ALL_COMPANIES as readonly string[]).includes(c))
  }, [companiesParam])

  const customer = searchParams.get("customer") || ""
  const carrier = searchParams.get("carrier") || ""

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
    updateUrl({ tab: tab === "pu-overview" ? null : tab })
  const setRange = (r: OcsRange) => updateUrl({ range: r === "mtd" ? null : r })
  const setStartDate = (d: string) => updateUrl({ s: d })
  const setEndDate = (d: string) => updateUrl({ e: d })
  const setCustomer = (c: string) => updateUrl({ customer: c || null })
  const setCarrier = (c: string) => updateUrl({ carrier: c || null })
  const setDivision = (d: OcsDivision) => {
    updateUrl({
      div: d === "All" ? null : d,
      sub: null,
      corp: null,
    })
  }
  const setSubTeams = (next: string[]) => {
    if (!next.length) updateUrl({ sub: null })
    else updateUrl({ sub: next.join(",") })
  }
  const setCorpTeams = (next: string[]) => {
    if (!next.length) updateUrl({ corp: null })
    else updateUrl({ corp: next.join(",") })
  }
  const setCompanies = (next: string[]) => {
    if (next.length === ALL_COMPANIES.length) updateUrl({ co: null })
    else updateUrl({ co: next.join(",") })
  }

  const filters: OcsFilters = useMemo(
    () => ({
      range,
      startDate: range === "custom" ? clampToYear(startDate) : undefined,
      endDate: range === "custom" ? clampToYear(endDate) : undefined,
      division,
      teams: division === "CORP" && corpTeams.length ? corpTeams : undefined,
      companies:
        companies.length === ALL_COMPANIES.length ? undefined : companies,
      subTeams: division === "DFW" && subTeams.length ? subTeams : undefined,
      customer: customer || undefined,
      carrier: carrier || undefined,
    }),
    [range, startDate, endDate, division, corpTeams, companies, subTeams, customer, carrier],
  )

  const { data: filterRes } = useOcsFilters({
    division,
    teams: division === "CORP" && corpTeams.length ? corpTeams : undefined,
    companies:
      companies.length === ALL_COMPANIES.length ? undefined : companies,
    subTeams: division === "DFW" && subTeams.length ? subTeams : undefined,
    customer: customer || undefined,
    carrier: carrier || undefined,
  })
  const opts = filterRes?.data
  const { data: freshnessRes } = useOcsFreshness()
  const fr = freshnessRes?.data

  const [customerInput, setCustomerInput] = useState("")
  const [carrierInput, setCarrierInput] = useState("")

  const customerSuggestions = useMemo(() => {
    const q = customerInput.trim().toLowerCase()
    if (!q || !opts?.customers) return []
    return opts.customers.filter((c) => c.toLowerCase().includes(q)).slice(0, 8)
  }, [customerInput, opts])
  const carrierSuggestions = useMemo(() => {
    const q = carrierInput.trim().toLowerCase()
    if (!q || !opts?.carriers) return []
    return opts.carriers.filter((c) => c.toLowerCase().includes(q)).slice(0, 8)
  }, [carrierInput, opts])

  const windowLabel =
    range === "custom"
      ? `${clampToYear(startDate)} → ${clampToYear(endDate)}`
      : range.replace("_", " ").toUpperCase()

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      {/* Desktop-only banner */}
      <div className="hidden bg-[#FEF3C7] px-4 py-2 text-xs text-[#92400E] [@media(max-width:1279px)]:block">
        OPs Customer Score is desktop-only. Open this page on a screen wider than 1280px.
      </div>

      <div className="mx-auto max-w-[1600px] px-4 py-4">
        {/* Top bar */}
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Link
              href="/"
              className="inline-flex items-center gap-1 text-xs text-[#6B7280] hover:text-[#111827]"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Home
            </Link>
            <h1 className="ml-3 text-lg font-semibold text-[#111827]">
              OPs Customer Score
            </h1>
          </div>
          <div className="text-[11px] text-[#6B7280]">
            {fr?.last_updated ? (
              <>Last refresh: {fmtTimestamp(fr.last_updated)} · {fmtCount(fr.rows_in_scope)} rows in scope</>
            ) : (
              <span className="inline-flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" /> loading freshness…
              </span>
            )}
          </div>
        </div>

        {/* Sticky filter bar */}
        <div className="sticky top-0 z-10 mb-4 rounded-md border border-[#E5E7EB] bg-white p-3 shadow-sm">
          <div className="flex flex-wrap items-end gap-3">
            {/* Division */}
            <div>
              <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">
                Division
              </div>
              <div className="mt-1 flex gap-1">
                {(["All", "CORP", "DFW"] as const).map((d) => (
                  <button
                    type="button"
                    key={d}
                    onClick={() => setDivision(d)}
                    className={`rounded-md border px-3 py-1 text-xs ${
                      division === d
                        ? "border-[#111827] bg-[#111827] text-white"
                        : "border-[#E5E7EB] bg-white text-[#374151]"
                    }`}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>

            {/* DFW sub-teams (only in DFW mode) */}
            {division === "DFW" && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">
                  DFW Sub-Team
                </div>
                <div className="mt-1 flex gap-1">
                  {DFW_SUB_TEAMS.map((t) => {
                    const active = subTeams.includes(t)
                    return (
                      <button
                        type="button"
                        key={t}
                        onClick={() =>
                          setSubTeams(
                            active
                              ? subTeams.filter((x) => x !== t)
                              : [...subTeams, t],
                          )
                        }
                        className={`rounded-md border px-2 py-1 text-xs ${
                          active
                            ? "border-[#111827] bg-[#111827] text-white"
                            : "border-[#E5E7EB] bg-white text-[#374151]"
                        }`}
                      >
                        {t}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* CORP sub-teams (only in CORP mode) */}
            {division === "CORP" && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">
                  CORP Sub-Team
                </div>
                <div className="mt-1 flex gap-1">
                  {CORP_SUB_TEAMS.map((t) => {
                    const active = corpTeams.includes(t)
                    return (
                      <button
                        type="button"
                        key={t}
                        onClick={() =>
                          setCorpTeams(
                            active
                              ? corpTeams.filter((x) => x !== t)
                              : [...corpTeams, t],
                          )
                        }
                        className={`rounded-md border px-2 py-1 text-xs ${
                          active
                            ? "border-[#111827] bg-[#111827] text-white"
                            : "border-[#E5E7EB] bg-white text-[#374151]"
                        }`}
                      >
                        {t}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Companies */}
            <div>
              <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">
                Company
              </div>
              <div className="mt-1 flex gap-1">
                {ALL_COMPANIES.map((c) => {
                  const active = companies.includes(c)
                  return (
                    <button
                      type="button"
                      key={c}
                      onClick={() => {
                        const next = active
                          ? companies.filter((x) => x !== c)
                          : [...companies, c]
                        setCompanies(next.length ? next : [...ALL_COMPANIES])
                      }}
                      className={`rounded-md border px-2 py-1 text-xs ${
                        active
                          ? "border-[#111827] bg-[#111827] text-white"
                          : "border-[#E5E7EB] bg-white text-[#374151]"
                      }`}
                    >
                      {c}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Customer combobox */}
            <div className="min-w-[260px]">
              <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">
                Customer
              </div>
              <div className="relative mt-1">
                <input
                  type="text"
                  className="w-full rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
                  placeholder={customer || "Type to search…"}
                  value={customerInput}
                  onChange={(e) => setCustomerInput(e.target.value)}
                  onBlur={() => setTimeout(() => setCustomerInput(""), 150)}
                />
                {customer && (
                  <button
                    type="button"
                    className="absolute right-1 top-1 rounded bg-[#F3F4F6] px-1.5 py-0.5 text-[10px] text-[#6B7280]"
                    onClick={() => {
                      setCustomer("")
                      setCustomerInput("")
                    }}
                  >
                    clear
                  </button>
                )}
                {customerSuggestions.length > 0 && (
                  <div className="absolute left-0 right-0 z-20 mt-1 max-h-48 overflow-y-auto rounded-md border border-[#E5E7EB] bg-white shadow-lg">
                    {customerSuggestions.map((c) => (
                      <button
                        type="button"
                        key={c}
                        onMouseDown={() => {
                          setCustomer(c)
                          setCustomerInput("")
                        }}
                        className="block w-full px-2 py-1 text-left text-xs hover:bg-[#F3F4F6]"
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {customer && (
                <div className="mt-1 truncate text-[11px] text-[#374151]">
                  Selected: <span className="font-medium">{customer}</span>
                </div>
              )}
            </div>

            {/* Carrier combobox */}
            <div className="min-w-[260px]">
              <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">
                Carrier
              </div>
              <div className="relative mt-1">
                <input
                  type="text"
                  className="w-full rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
                  placeholder={carrier || "Type to search…"}
                  value={carrierInput}
                  onChange={(e) => setCarrierInput(e.target.value)}
                  onBlur={() => setTimeout(() => setCarrierInput(""), 150)}
                />
                {carrier && (
                  <button
                    type="button"
                    className="absolute right-1 top-1 rounded bg-[#F3F4F6] px-1.5 py-0.5 text-[10px] text-[#6B7280]"
                    onClick={() => {
                      setCarrier("")
                      setCarrierInput("")
                    }}
                  >
                    clear
                  </button>
                )}
                {carrierSuggestions.length > 0 && (
                  <div className="absolute left-0 right-0 z-20 mt-1 max-h-48 overflow-y-auto rounded-md border border-[#E5E7EB] bg-white shadow-lg">
                    {carrierSuggestions.map((c) => (
                      <button
                        type="button"
                        key={c}
                        onMouseDown={() => {
                          setCarrier(c)
                          setCarrierInput("")
                        }}
                        className="block w-full px-2 py-1 text-left text-xs hover:bg-[#F3F4F6]"
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {carrier && (
                <div className="mt-1 truncate text-[11px] text-[#374151]">
                  Selected: <span className="font-medium">{carrier}</span>
                </div>
              )}
            </div>

            {/* Date preset */}
            <div>
              <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">
                Date
              </div>
              <div className="mt-1 flex gap-1">
                {(
                  [
                    ["mtd", "MTD"],
                    ["last_month", "Last Month"],
                    ["ytd", "YTD"],
                    ["custom", "Custom"],
                  ] as const
                ).map(([k, label]) => (
                  <button
                    type="button"
                    key={k}
                    onClick={() => setRange(k)}
                    className={`rounded-md border px-2 py-1 text-xs ${
                      range === k
                        ? "border-[#111827] bg-[#111827] text-white"
                        : "border-[#E5E7EB] bg-white text-[#374151]"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* Custom date inputs */}
            {range === "custom" && (
              <div className="flex items-end gap-2">
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">
                    Start
                  </div>
                  <input
                    type="date"
                    min={YEAR_START}
                    max={YEAR_END}
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="mt-1 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
                  />
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">
                    End
                  </div>
                  <input
                    type="date"
                    min={YEAR_START}
                    max={YEAR_END}
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="mt-1 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
                  />
                </div>
              </div>
            )}

            <div className="ml-auto text-[11px] text-[#6B7280]">
              Window: <span className="font-mono">{windowLabel}</span>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="mb-3 flex flex-wrap gap-1 border-b border-[#E5E7EB]">
          {TABS.map((t) => (
            <button
              type="button"
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`rounded-t-md px-3 py-1.5 text-xs ${
                activeTab === t.key
                  ? "border border-[#E5E7EB] border-b-white bg-white text-[#111827] font-medium"
                  : "text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === "pu-overview" && <PuOverview filters={filters} />}
        {activeTab === "del-overview" && <DelOverview filters={filters} />}
        {activeTab === "pu-detail" && <Detail filters={filters} side="pu" />}
        {activeTab === "del-detail" && <Detail filters={filters} side="del" />}
      </div>
    </div>
  )
}

export default function OpsCustomerScorePage() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["ops-customer-score"]]}>
      <Suspense
        fallback={
          <div className="flex min-h-screen items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        }
      >
        <OcsContent />
      </Suspense>
    </RoleGuard>
  )
}
