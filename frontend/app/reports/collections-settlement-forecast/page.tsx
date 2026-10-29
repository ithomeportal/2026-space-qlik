"use client"

import { Suspense, useCallback } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, HandCoins, Loader2 } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import { useThisWeek } from "@/lib/collections-settlement-forecast-api"
import { AccuracyPanel } from "./AccuracyPanel"
import { CustomersPanel } from "./CustomersPanel"
import { ThisWeekPanel } from "./ThisWeekPanel"
import { WeeksPanel } from "./WeeksPanel"
import { FavoriteToggle } from "@/components/FavoriteToggle"

const TABS = [
  { k: "this-week", label: "This Week" },
  { k: "weeks", label: "13-Week Forecast" },
  { k: "customers", label: "By Customer" },
  { k: "accuracy", label: "Forecast vs Actual" },
] as const
type TabKey = (typeof TABS)[number]["k"]

/** A page over synced tables needs a visible "data as of" (§54). */
function FreshnessBar() {
  const { data } = useThisWeek()
  const f = data?.meta.freshness
  if (!f) return null
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[#6B7280]">
      <span>AR snapshot {f.ar_snapshot_date ?? "—"}</span>
      <span>· receipts through {f.latest_receipt_gl_date ?? "—"}</span>
      <span>· last read from McLeod {f.receipts_checked_at ?? "—"}</span>
      <span>· settlements {f.settlements_snapshot_date ?? "—"}</span>
      <span>· AP {f.ap_snapshot_date ?? "—"}</span>
      <span>· shipped loads {f.shipped_as_of ?? "—"}</span>
      {f.failed_sources.length > 0 && (
        <span className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[#92400E]">
          unavailable: {f.failed_sources.join(", ")}
        </span>
      )}
    </div>
  )
}

function ForecastContent() {
  const router = useRouter()
  const pathname = usePathname()
  const params = useSearchParams()
  const raw = params.get("tab")
  const tab: TabKey = TABS.some((t) => t.k === raw) ? (raw as TabKey) : "this-week"
  const setTab = useCallback(
    (k: TabKey) => router.replace(k === "this-week" ? pathname : `${pathname}?tab=${k}`, { scroll: false }),
    [router, pathname],
  )

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link href="/" className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]">
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <HandCoins className="h-4 w-4 text-[#1B3A5C]" />
        <h1 className="text-sm font-semibold text-[#1B3A5C]">Collections Settlement Forecast<FavoriteToggle /></h1>
        <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-xs text-[#1D4ED8]">UNILINK US · TMS</span>
      </div>
      <div className="mx-auto w-full max-w-[1600px] space-y-4 px-6 py-4">
        <FreshnessBar />
        <div className="flex rounded-lg border border-[#E5E7EB] bg-white text-xs w-fit">
          {TABS.map((t) => (
            <button
              key={t.k}
              onClick={() => setTab(t.k)}
              className={`px-4 py-2 ${
                tab === t.k ? "bg-[#1B3A5C] font-semibold text-white" : "text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        {tab === "this-week" && <ThisWeekPanel />}
        {tab === "weeks" && <WeeksPanel />}
        {tab === "customers" && <CustomersPanel />}
        {tab === "accuracy" && <AccuracyPanel />}
      </div>
    </div>
  )
}

export default function CollectionsSettlementForecastPage() {
  return (
    <ReportGuard reportKey="collections-settlement-forecast">
      <Suspense
        fallback={
          <div className="flex h-[60vh] items-center justify-center text-[#6B7280]">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        }
      >
        <ForecastContent />
      </Suspense>
    </ReportGuard>
  )
}
