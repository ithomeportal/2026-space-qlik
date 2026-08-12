"use client"

import { Suspense, useCallback, useMemo } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Loader2, Store } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import { MultiSelectChips } from "@/components/MultiSelectChips"
import {
  useHdSpotFilterOptions,
  useHdSpotFreshness,
  type HdSpotFilters,
  type HdSpotRange,
  type HdSpotStatus,
} from "@/lib/hd-spot-api"
import { KpiCards } from "./KpiCards"
import { AwardedChart } from "./AwardedChart"
import { DataTable } from "./DataTable"

// The live `homedepot` feed's first full month. Earlier data is the frozen
// `legacy_hd` import, which carries no volume — see the router docstring.
const DATA_FLOOR = "2026-03-01"
const YEAR_END = "2026-12-31"

const RANGES: { k: HdSpotRange; label: string }[] = [
  { k: "today", label: "Today" },
  { k: "yesterday", label: "Yesterday" },
  { k: "mtd", label: "Month to Date" },
  { k: "last_month", label: "Last Month" },
  { k: "custom", label: "Custom" },
]

const STATUS_LABELS: Record<HdSpotStatus, string> = {
  cancelled: "Cancelled",
  covered: "Covered",
  pending: "Pending to Cover",
}
const STATUS_VALUES = Object.keys(STATUS_LABELS) as HdSpotStatus[]

function pad(n: number) {
  return String(n).padStart(2, "0")
}
function iso(d: Date) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function clamp(v: string) {
  if (v < DATA_FLOOR) return DATA_FLOOR
  if (v > YEAR_END) return YEAR_END
  return v
}

function HdSpotContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  // "Month to Date must be selected by default" (Request 2).
  const range = (searchParams.get("range") as HdSpotRange) || "mtd"
  const startDate = clamp(searchParams.get("s") || iso(new Date()).slice(0, 8) + "01")
  const endDate = clamp(searchParams.get("e") || iso(new Date()))
  const equipment = searchParams.getAll("eq")
  const status = searchParams.getAll("st") as HdSpotStatus[]

  const { data: optsRes, isLoading: loadingFilters } = useHdSpotFilterOptions()
  const { data: freshRes } = useHdSpotFreshness()
  const opts = optsRes?.data
  const fresh = freshRes?.data

  const updateUrl = useCallback(
    (patch: Record<string, string | string[] | null | undefined>) => {
      const next = new URLSearchParams(searchParams.toString())
      for (const [k, v] of Object.entries(patch)) {
        next.delete(k)
        if (Array.isArray(v)) for (const item of v) next.append(k, item)
        else if (v !== null && v !== undefined && v !== "") next.set(k, v)
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [searchParams, router, pathname]
  )

  const filters: HdSpotFilters = useMemo(
    () => ({ range, startDate, endDate, equipment, status }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [range, startDate, endDate, equipment.join("|"), status.join("|")]
  )

  const windowLabel = useMemo(() => {
    if (range === "custom") return `${startDate} → ${endDate}`
    return RANGES.find((r) => r.k === range)?.label ?? ""
  }, [range, startDate, endDate])

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
          <Store className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">HD Spot</h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-xs text-[#1D4ED8]">
            HOME DEPOT
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          <span>{windowLabel}</span>
          {/* A page over a synced table needs a visible freshness signal, or a
              dead pipeline and a quiet day look identical (§54). */}
          {fresh?.spot && (
            <span
              className={
                fresh.is_stale
                  ? "rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[#92400E]"
                  : ""
              }
              title={`Spot feed ${fresh.spot}${
                fresh.gold ? ` · McLeod ${fresh.gold}` : ""
              }`}
            >
              Data as of {fresh.spot.slice(0, 16).replace("T", " ")}
              {fresh.is_stale ? " · stale" : ""}
            </span>
          )}
        </div>
      </div>

      {/* Sticky filter bar */}
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
                  onClick={() => updateUrl({ range: opt.k === "mtd" ? null : opt.k })}
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
                  min={opts?.data_floor ?? DATA_FLOOR}
                  max={YEAR_END}
                  value={startDate}
                  onChange={(ev) => updateUrl({ s: ev.target.value })}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
                <span className="text-[#6B7280]">→</span>
                <input
                  type="date"
                  min={opts?.data_floor ?? DATA_FLOOR}
                  max={YEAR_END}
                  value={endDate}
                  onChange={(ev) => updateUrl({ e: ev.target.value })}
                  className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
                />
              </div>
            )}
          </div>

          <MultiSelectChips
            label="Equipment"
            options={opts?.equipment ?? []}
            selected={equipment}
            onChange={(v: string[]) => updateUrl({ eq: v })}
            placeholder="All equipment"
            width={200}
            disabled={loadingFilters}
          />

          {/* Raw values stay on the wire; optionLabels only changes the rendered
              text, so V/A/D+P keep their request-mandated display names. */}
          <MultiSelectChips
            label="Status"
            options={STATUS_VALUES}
            selected={status}
            onChange={(v: string[]) => updateUrl({ st: v })}
            optionLabels={STATUS_LABELS}
            placeholder="All statuses"
            width={220}
            disabled={loadingFilters}
          />

          {status.length > 0 && (
            <span className="text-[10px] text-[#92400E]">
              Status scopes the money columns only — a quote that was never
              awarded has no order status.
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-6 px-6 py-6">
        <KpiCards filters={filters} />
        <AwardedChart filters={filters} />
        <DataTable filters={filters} />
      </div>
    </div>
  )
}

export default function HdSpotPage() {
  return (
    <ReportGuard reportKey="hd-spot">
      <Suspense
        fallback={
          <div className="flex min-h-[calc(100vh-64px)] items-center justify-center bg-[#F9FAFB]">
            <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
          </div>
        }
      >
        <HdSpotContent />
      </Suspense>
    </ReportGuard>
  )
}
