"use client"

import { Suspense, useCallback, useMemo } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import {
  ArrowLeft,
  ClipboardList,
  Loader2,
  ScrollText,
  Stethoscope,
  TrendingUp,
  Users,
} from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import { Tab1Scorecards } from "./Tab1Scorecards"
import { Tab2Service } from "./Tab2Service"
import { Tab3TopLanes } from "./Tab3TopLanes"
import { Tab4CustomerDev } from "./Tab4CustomerDev"
import { Tab5TeamDev } from "./Tab5TeamDev"

type TabKey = "scorecards" | "service" | "lanes" | "customer-dev" | "team-dev"

const TABS: { k: TabKey; label: string; icon: React.ReactNode }[] = [
  { k: "scorecards", label: "Scorecards", icon: <ScrollText className="h-3.5 w-3.5" /> },
  { k: "service", label: "Service", icon: <Stethoscope className="h-3.5 w-3.5" /> },
  { k: "lanes", label: "Top 10 lanes", icon: <TrendingUp className="h-3.5 w-3.5" /> },
  { k: "customer-dev", label: "Customer Dev", icon: <ClipboardList className="h-3.5 w-3.5" /> },
  { k: "team-dev", label: "Team Dev", icon: <Users className="h-3.5 w-3.5" /> },
]

function KamPerformanceContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const tabParam = searchParams.get("tab") as TabKey | null
  const tab: TabKey = useMemo(() => {
    if (tabParam && TABS.some((t) => t.k === tabParam)) return tabParam
    return "scorecards"
  }, [tabParam])

  const setTab = useCallback(
    (k: TabKey) => {
      const next = new URLSearchParams(searchParams.toString())
      if (k === "scorecards") next.delete("tab")
      else next.set("tab", k)
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [searchParams, router, pathname],
  )

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
          <Users className="h-4 w-4 text-[#1B3A5C]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">
            KAM Performance - DFW
          </h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-[10px] text-[#1E40AF]">
            Per-user
          </span>
        </div>
      </div>

      {/* Tab nav */}
      <div className="sticky top-0 z-10 border-b border-[#E5E7EB] bg-white shadow-sm">
        <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-center gap-2 px-6 py-2">
          {TABS.map((t) => (
            <button
              key={t.k}
              onClick={() => setTab(t.k)}
              className={`inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs ${
                tab === t.k
                  ? "bg-[#1B3A5C] text-white shadow-sm"
                  : "border border-[#E5E7EB] text-[#374151] hover:bg-[#F9FAFB]"
              }`}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="mx-auto w-full max-w-[1920px] px-6 py-4">
        {tab === "scorecards" && <Tab1Scorecards />}
        {tab === "service" && <Tab2Service />}
        {tab === "lanes" && <Tab3TopLanes />}
        {tab === "customer-dev" && <Tab4CustomerDev />}
        {tab === "team-dev" && <Tab5TeamDev />}
      </div>
    </div>
  )
}

export default function KamPerformanceDfwPage() {
  return (
    <ReportGuard reportKey="kam-performance-dfw">
      <Suspense
        fallback={
          <div className="flex h-[60vh] items-center justify-center text-[#6B7280]">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        }
      >
        <KamPerformanceContent />
      </Suspense>
    </ReportGuard>
  )
}
