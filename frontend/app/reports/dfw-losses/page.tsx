"use client"

import { Suspense, useCallback, useMemo } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Loader2, TrendingDown } from "lucide-react"
import {
  useDfwLossesFilters,
  type DfwLossesFilters,
  type DfwLossesRange,
} from "@/lib/dfw-losses-api"
import { ReportGuard } from "@/components/ReportGuard"
import { MultiSelectChips } from "@/components/MultiSelectChips"
import { DailyTable } from "./DailyTable"
import { LanesTable } from "./LanesTable"

const YEAR_START = "2026-01-01"
const YEAR_END = "2026-12-31"

const RANGES: { k: DfwLossesRange; label: string }[] = [
  { k: "mtd", label: "MTD" },
  { k: "wtd", label: "WTD" },
  { k: "last_month", label: "Last Month" },
  { k: "ytd", label: "YTD" },
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

function parseCsv(raw: string | null): string[] {
  if (!raw) return []
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
}

function DfwLossesContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  const range = (searchParams.get("range") as DfwLossesRange) || "mtd"
  const startDate = searchParams.get("s") || monthStartIso()
  const endDate = searchParams.get("e") || clampToYear(todayIso())
  const contractTypes = useMemo(
    () => parseCsv(searchParams.get("contract")),
    [searchParams],
  )
  const customerNames = useMemo(
    () => parseCsv(searchParams.get("customer")),
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

  const setRange = (r: DfwLossesRange) => updateUrl({ range: r === "mtd" ? null : r })
  const setStartDate = (d: string) => updateUrl({ s: d })
  const setEndDate = (d: string) => updateUrl({ e: d })
  const setContractTypes = (next: string[]) =>
    updateUrl({ contract: next.length ? next.join(",") : null })
  const setCustomerNames = (next: string[]) =>
    updateUrl({ customer: next.length ? next.join(",") : null })

  const filters: DfwLossesFilters = useMemo(
    () => ({
      range,
      startDate: range === "custom" ? clampToYear(startDate) : undefined,
      endDate: range === "custom" ? clampToYear(endDate) : undefined,
      contractTypes,
      customerNames,
    }),
    [range, startDate, endDate, contractTypes, customerNames],
  )

  const { data: filterRes, isLoading: loadingFilters } = useDfwLossesFilters(filters)
  const opts = filterRes?.data
  const win = opts?.window

  const windowLabel = win
    ? `${win.start} → ${win.end}`
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
          <h1 className="text-sm font-semibold text-[#1B3A5C]">DFW Losses</h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-xs text-[#1D4ED8]">
            TEAM-DFW
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          <span>
            {windowLabel}
            {contractTypes.length ? ` · Contract: ${contractTypes.join(", ")}` : ""}
            {customerNames.length
              ? ` · ${customerNames.length} customer${customerNames.length > 1 ? "s" : ""}`
              : ""}
          </span>
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

          <MultiSelectChips
            label="Contract"
            options={opts?.contract_types ?? []}
            selected={contractTypes}
            onChange={setContractTypes}
            placeholder="All contract types"
            width={160}
            disabled={loadingFilters}
          />

          <MultiSelectChips
            label="Customer"
            options={opts?.customers ?? []}
            selected={customerNames}
            onChange={setCustomerNames}
            placeholder="All customers"
            width={260}
            disabled={loadingFilters}
          />

          {loadingFilters && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-6 px-6 py-6">
        <DailyTable filters={filters} />
        <LanesTable filters={filters} />
      </div>
    </div>
  )
}

export default function DfwLossesPage() {
  return (
    <ReportGuard reportKey="dfw-losses">
      <Suspense
        fallback={
          <div className="flex min-h-[calc(100vh-64px)] items-center justify-center bg-[#F9FAFB]">
            <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
          </div>
        }
      >
        <DfwLossesContent />
      </Suspense>
    </ReportGuard>
  )
}
