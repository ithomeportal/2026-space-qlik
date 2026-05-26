"use client"

import { useState } from "react"
import Link from "next/link"
import { ArrowLeft, HandCoins, Loader2, Settings, Lock } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import { useBonusFilters, useBonusReport } from "@/lib/bonus-api"
import { BRAND, BRAND_DARK } from "./format"
import { KpiStrip } from "./components/KpiStrip"
import { CriteriaGuide } from "./components/CriteriaGuide"
import { TeamBlock } from "./components/TeamBlock"
import { AfterhoursCard } from "./components/AfterhoursCard"
import { BestPractice } from "./components/BestPractice"
import { RosterEditor } from "./components/RosterEditor"
import { ErrorBanner } from "./ErrorBanner"

export default function BonusCalculatorPage() {
  return (
    <ReportGuard reportKey="bonus-calculator">
      <BonusCalculatorContent />
    </ReportGuard>
  )
}

function BonusCalculatorContent() {
  const [period, setPeriod] = useState<string | undefined>(undefined)
  const [teamFilter, setTeamFilter] = useState<string>("")
  const [editorOpen, setEditorOpen] = useState(false)

  const { data: filtersRes } = useBonusFilters()
  const filters = filtersRes?.data
  const { data: reportRes, isLoading, isError } = useBonusReport(period)
  const report = reportRes?.data

  const effectivePeriod = period ?? filters?.currentPeriod
  const visibleTeams = report?.teams.filter((t) => !teamFilter || t.id === teamFilter) ?? []
  const locked = report?.lock.status === "approved"

  return (
    <div className="min-h-[calc(100vh-64px)] bg-[#F7F7FB]">
      {/* Brand header */}
      <div className="px-4 pt-4">
        <Link href="/" className="mb-3 inline-flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]">
          <ArrowLeft className="h-4 w-4" /> Back
        </Link>
        <div
          className="flex flex-wrap items-center justify-between gap-4 rounded-2xl px-6 py-5 text-white shadow-md"
          style={{ background: `linear-gradient(110deg, ${BRAND_DARK}, ${BRAND})` }}
        >
          <div>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white/20 px-3 py-1 text-[10px] font-bold uppercase tracking-[0.14em]">
              <HandCoins className="h-3.5 w-3.5" /> Corporate Bonus Module
            </span>
            <h1 className="mt-2 text-3xl font-extrabold tracking-tight">Bonus Calculator</h1>
          </div>
          <div className="flex items-center gap-2">
            {locked && (
              <span className="inline-flex items-center gap-1 rounded-full bg-white/20 px-3 py-1.5 text-xs font-semibold">
                <Lock className="h-3.5 w-3.5" /> Locked · approved
              </span>
            )}
            <button
              onClick={() => setEditorOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-full bg-white/95 px-4 py-2 text-sm font-semibold text-[#561195] hover:bg-white"
            >
              <Settings className="h-4 w-4" /> HR Settings
            </button>
          </div>
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1400px] space-y-5 px-4 py-5">
        {/* Report period + filters */}
        <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#EDE9FE] bg-white px-5 py-4 shadow-sm">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#8B5CF6]">Report Period</p>
            <p className="text-xl font-bold text-[#1F2937]">{report?.period.label ?? "—"}</p>
            <p className="text-xs text-[#6B7280]">{report?.source ?? "Live datalake; McLeod TMS connected"}</p>
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <label className="text-xs font-semibold text-[#6B7280]">
              Period
              <select
                value={effectivePeriod ?? ""}
                onChange={(e) => setPeriod(e.target.value)}
                className="mt-1 block rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-sm"
              >
                {(filters?.periods ?? []).map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs font-semibold text-[#6B7280]">
              Filter team
              <select
                value={teamFilter}
                onChange={(e) => setTeamFilter(e.target.value)}
                className="mt-1 block rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-sm"
              >
                <option value="">All teams</option>
                {(filters?.teams ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        {isLoading && (
          <div className="flex items-center justify-center py-24 text-[#6B7280]">
            <Loader2 className="mr-2 h-6 w-6 animate-spin" /> Calculating bonuses…
          </div>
        )}
        {isError && <ErrorBanner />}

        {report && (
          <>
            <KpiStrip report={report} />
            <CriteriaGuide report={report} />
            {visibleTeams.map((team) => (
              <TeamBlock key={team.id} team={team} report={report} />
            ))}
            <AfterhoursCard report={report} />
            <BestPractice />
          </>
        )}
      </div>

      {editorOpen && <RosterEditor period={effectivePeriod} onClose={() => setEditorOpen(false)} />}
    </div>
  )
}
