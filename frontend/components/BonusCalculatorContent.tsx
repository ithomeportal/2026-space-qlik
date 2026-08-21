"use client"

import { useState } from "react"
import Link from "next/link"
import { ArrowLeft, HandCoins, Loader2, Settings, Lock } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import { BonusApiProvider, useBonusFilters, useBonusReport } from "@/lib/bonus-api"
import { BRAND, BRAND_DARK } from "@/app/reports/bonus-calculator/format"
import { KpiStrip } from "@/app/reports/bonus-calculator/components/KpiStrip"
import { CriteriaGuide } from "@/app/reports/bonus-calculator/components/CriteriaGuide"
import { TeamBlock } from "@/app/reports/bonus-calculator/components/TeamBlock"
import { AfterhoursCard } from "@/app/reports/bonus-calculator/components/AfterhoursCard"
import { BestPractice } from "@/app/reports/bonus-calculator/components/BestPractice"
import { RosterEditor } from "@/app/reports/bonus-calculator/components/RosterEditor"
import { HistoryTab } from "@/app/reports/bonus-calculator/components/HistoryTab"
import { RulesTab } from "@/app/reports/bonus-calculator/components/RulesTab"
import { ErrorBanner } from "@/app/reports/bonus-calculator/ErrorBanner"

type TabKey = "calculator" | "history" | "rules"

const TABS: { key: TabKey; label: string }[] = [
  { key: "calculator", label: "Calculator" },
  { key: "history", label: "History" },
  { key: "rules", label: "Rules" },
]

/**
 * Shared page shell for both bonus calculators (Bruno PDF 2026-08-20).
 *
 * `apiPrefix` flows through `BonusApiProvider`, so every hook — and every
 * React Query cache key — points at that calculator's own backend router and
 * its own `bonus_*` tables. The two must never share a cache entry: the values
 * are payroll, and a stale one from the other division looks entirely valid.
 */
export function BonusCalculatorPage({
  reportKey = "bonus-calculator",
  apiPrefix = "custom/bonus-calculator",
  title = "Bonus Calculator",
  eyebrow = "Corporate Bonus Module",
}: {
  reportKey?: string
  apiPrefix?: string
  title?: string
  eyebrow?: string
} = {}) {
  return (
    <ReportGuard
      reportKey={reportKey}
      // Sensitive payroll report — override the default banner (which reveals
      // the required TagRoles) with a neutral message that discloses nothing
      // and points the user to their manager. Bruno 2026-07-07.
      fallback={
        <div className="flex min-h-[calc(100vh-64px)] flex-col items-center justify-center bg-[#F9FAFB] p-8">
          <div className="max-w-md rounded-xl border border-[#E5E7EB] bg-white p-8 text-center shadow-sm">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#F9FAFB] ring-1 ring-[#E5E7EB]">
              <Lock className="h-5 w-5 text-[#1B3A5C]" />
            </div>
            <h2 className="text-xl font-semibold text-[#1B3A5C]">Access restricted</h2>
            <p className="mt-2 text-sm text-[#6B7280]">
              You don&apos;t have access to this report. Please review with your Manager.
            </p>
          </div>
        </div>
      }
    >
      <BonusApiProvider prefix={apiPrefix}>
        <BonusCalculatorContent title={title} eyebrow={eyebrow} />
      </BonusApiProvider>
    </ReportGuard>
  )
}

function BonusCalculatorContent({ title, eyebrow }: { title: string; eyebrow: string }) {
  const [period, setPeriod] = useState<string | undefined>(undefined)
  const [teamFilter, setTeamFilter] = useState<string>("")
  const [editorOpen, setEditorOpen] = useState(false)
  const [tab, setTab] = useState<TabKey>("calculator")

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
              <HandCoins className="h-3.5 w-3.5" /> {eyebrow}
            </span>
            <h1 className="mt-2 text-3xl font-extrabold tracking-tight">{title}</h1>
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
        {/* Tab switcher (Bruno 2026-05-28: + History + Rules). */}
        <div className="flex gap-1 border-b border-[#EDE9FE]">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`border-b-2 px-4 py-2 text-sm font-semibold transition-colors ${
                tab === t.key
                  ? "border-[#561195] text-[#561195]"
                  : "border-transparent text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "history" && <HistoryTab />}

        {tab === "rules" &&
          (report ? (
            <RulesTab report={report} />
          ) : (
            <div className="flex items-center justify-center py-24 text-[#6B7280]">
              <Loader2 className="mr-2 h-6 w-6 animate-spin" /> Loading rules…
            </div>
          ))}

        {tab === "calculator" && (
          <>
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
          </>
        )}
      </div>

      {editorOpen && <RosterEditor period={effectivePeriod} onClose={() => setEditorOpen(false)} />}
    </div>
  )
}
