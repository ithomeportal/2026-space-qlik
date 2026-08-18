"use client"

import { Suspense, useCallback, useMemo } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, ClipboardCheck, FlaskConical, Loader2 } from "lucide-react"
import {
  SCENARIO_STEPS,
  useBookerFilterOptions,
  type BookerFilters,
  type BookerRange,
  type BookerScopeFilters,
  type ScenarioStep,
} from "@/lib/booker-scorecard-api"
import { ReportGuard } from "@/components/ReportGuard"
import { MultiSelectChips } from "@/components/MultiSelectChips"
import { KpiCards } from "./KpiCards"
import { WeeklyChart } from "./WeeklyChart"
import { OrdersTable } from "./OrdersTable"
import { ActionPlan } from "./ActionPlan"
import { DataFreshness } from "./DataFreshness"
import { ScenarioPanel } from "./ScenarioPanel"

const YEAR_START = "2026-01-01"
const YEAR_END = "2026-12-31"

type TabKey = "scorecard" | "scenario"

const TABS: { k: TabKey; label: string; icon: typeof ClipboardCheck }[] = [
  { k: "scorecard", label: "Scorecard", icon: ClipboardCheck },
  { k: "scenario", label: "Scenario", icon: FlaskConical },
]

const RANGES: { k: BookerRange; label: string }[] = [
  { k: "today", label: "Today" },
  { k: "wtd", label: "Week to Date" },
  { k: "mtd", label: "Month to Date" },
  { k: "custom", label: "Custom" },
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

/**
 * URL <-> multi-select. The URL uses a `|` separator, NOT a comma: customer
 * names contain commas ("CONAGRA FOODS PACKAGED FOODS, LLC") and a comma-split
 * would silently shred them into halves that match nothing (§45). Only the URL
 * encoding is affected — the wire format is repeated query params either way.
 */
const SEP = "|"

function parseList(raw: string | null): string[] {
  if (!raw) return []
  return raw
    .split(SEP)
    .map((s) => s.trim())
    .filter(Boolean)
}

function BookerScorecardContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  // Tab lives in the URL like every other bit of state on this page, so a
  // scenario view is shareable and the back button works (house pattern:
  // kam-performance-dfw). The default tab omits the param entirely.
  const tab: TabKey = searchParams.get("tab") === "scenario" ? "scenario" : "scorecard"
  const stepRaw = Number(searchParams.get("adj"))
  const step: ScenarioStep = (SCENARIO_STEPS as readonly number[]).includes(stepRaw)
    ? (stepRaw as ScenarioStep)
    : SCENARIO_STEPS[0]

  const range = (searchParams.get("range") as BookerRange) || "mtd"
  const startDate = searchParams.get("s") || monthStartIso()
  const endDate = searchParams.get("e") || clampToYear(todayIso())
  const contractTypes = useMemo(
    () => parseList(searchParams.get("contract")),
    [searchParams],
  )
  const customers = useMemo(
    () => parseList(searchParams.get("customer")),
    [searchParams],
  )
  const postedBy = useMemo(
    () => parseList(searchParams.get("poster")),
    [searchParams],
  )

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

  const setTab = (t: TabKey) => updateUrl({ tab: t === "scorecard" ? null : t })
  const setStep = (v: ScenarioStep) => updateUrl({ adj: String(v) })

  const setRange = (r: BookerRange) =>
    updateUrl({ range: r === "mtd" ? null : r })
  const setList = (key: string) => (next: string[]) =>
    updateUrl({ [key]: next.length ? next.join(SEP) : null })

  const filters: BookerFilters = useMemo(
    () => ({
      range,
      startDate: range === "custom" ? clampToYear(startDate) : undefined,
      endDate: range === "custom" ? clampToYear(endDate) : undefined,
      contractTypes,
      customers,
      postedBy,
    }),
    [range, startDate, endDate, contractTypes, customers, postedBy],
  )

  // The chart takes the same scope MINUS the date filter (Bruno Request 6).
  const scope: BookerScopeFilters = useMemo(
    () => ({ contractTypes, customers, postedBy }),
    [contractTypes, customers, postedBy],
  )

  const { data: optRes, isLoading: loadingFilters } =
    useBookerFilterOptions(filters)
  const opts = optRes?.data
  const win = opts?.window

  const windowLabel = win
    ? `${win.start} → ${win.end}`
    : range === "custom"
      ? `${clampToYear(startDate)} → ${clampToYear(endDate)}`
      : RANGES.find((r) => r.k === range)?.label ?? range

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
          <ClipboardCheck className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">
            Booker Performance Scorecard
          </h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-xs text-[#1D4ED8]">
            TEAM-DFW
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          <span>{windowLabel}</span>
          <DataFreshness />
        </div>
      </div>

      {/* Filter bar */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-4 px-6 py-3">
          <div className="flex items-center gap-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Date
            </label>
            <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
              {RANGES.map((opt) => (
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
                  onChange={(e) => updateUrl({ s: e.target.value })}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
                <span className="text-[#6B7280]">→</span>
                <input
                  type="date"
                  min={YEAR_START}
                  max={YEAR_END}
                  value={endDate}
                  onChange={(e) => updateUrl({ e: e.target.value })}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
              </div>
            )}
          </div>

          <MultiSelectChips
            label="Customer"
            options={opts?.customers ?? []}
            selected={customers}
            onChange={setList("customer")}
            placeholder="All customers"
            width={240}
            disabled={loadingFilters}
          />

          <MultiSelectChips
            label="Contract"
            options={opts?.contract_types ?? []}
            selected={contractTypes}
            onChange={setList("contract")}
            placeholder="All contract types"
            width={170}
            disabled={loadingFilters}
          />

          <MultiSelectChips
            label="Posted By"
            options={opts?.posted_by ?? []}
            selected={postedBy}
            onChange={setList("poster")}
            placeholder="All bookers"
            width={220}
            disabled={loadingFilters}
          />

          {loadingFilters && (
            <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />
          )}
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-6 px-6 py-6">
        <div className="flex gap-1 border-b border-[#E5E7EB]">
          {TABS.map((t) => (
            <button
              key={t.k}
              onClick={() => setTab(t.k)}
              className={`flex items-center gap-1.5 px-4 py-2 text-sm ${
                tab === t.k
                  ? "-mb-px border-b-2 border-[#1B3A5C] font-semibold text-[#1B3A5C]"
                  : "text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              <t.icon className="h-4 w-4" />
              {t.label}
            </button>
          ))}
        </div>

        {tab === "scorecard" && (
          <>
            <KpiCards filters={filters} />
            <WeeklyChart scope={scope} />
            <OrdersTable filters={filters} />
            {/* Stays on this tab only: it is ONE shared per-user note row, so
                rendering it twice would put two editors on one record. */}
            <ActionPlan />
          </>
        )}

        {tab === "scenario" && (
          <ScenarioPanel
            filters={filters}
            scope={scope}
            step={step}
            onStepChange={setStep}
          />
        )}
      </div>
    </div>
  )
}

export default function BookerScorecardPage() {
  return (
    <ReportGuard reportKey="booker-performance-scorecard">
      <Suspense
        fallback={
          <div className="flex min-h-[calc(100vh-64px)] items-center justify-center bg-[#F9FAFB]">
            <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
          </div>
        }
      >
        <BookerScorecardContent />
      </Suspense>
    </ReportGuard>
  )
}
