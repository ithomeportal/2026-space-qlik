"use client"

import { BookOpen, CalendarRange, Trophy } from "lucide-react"
import type { BonusReport } from "@/lib/bonus-api"
import { BRAND, COLORS } from "../format"
import { CriteriaGuide } from "./CriteriaGuide"

// Bruno 2026-05-28: a static "Rules" tab that documents how the module works —
// the bonus rules, the period/week definition, and the data cutoff — so users
// understand what the app is doing.

function RuleCard({
  Icon,
  title,
  children,
}: {
  Icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-2xl border border-[#EDE9FE] bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2">
        <Icon className="h-5 w-5" style={{ color: COLORS.cardTitle }} />
        <h2 className="text-lg font-bold text-[#1F2937]">{title}</h2>
      </div>
      <div className="mt-3 space-y-2 text-sm leading-relaxed text-[#475569]">{children}</div>
    </div>
  )
}

export function RulesTab({ report }: { report: BonusReport }) {
  // ⚠ 18.5% corporate, 15.0% on DFW — read off the ladder the server sent, so
  // the prose can never contradict the bracket table it sits next to.
  const mb = report.criteria?.marginBrackets
  const entryMarginLabel = mb?.length ? `${(mb[0].threshold * 100).toFixed(1)}%` : "the entry"
  return (
    <div className="space-y-4">
      <RuleCard Icon={BookOpen} title="Regular Bonus">
        <ul className="ml-4 list-disc space-y-1.5">
          <li>
            <strong>KAM:</strong> reach a minimum of 100 loads in the week.
          </li>
          <li>
            <strong>Freight Match:</strong> needs a minimum of 100 loads in the week and an{" "}
            {entryMarginLabel} margin; the margin bracket pays only once the 100-load minimum is met.
          </li>
          <li>
            <strong>Tracking &amp; Tracing:</strong> needs a minimum of 100 loads in the week
            plus the current-month pickup and delivery service average; below 100 loads no
            service bonus applies that week.
          </li>
        </ul>
      </RuleCard>

      <RuleCard Icon={Trophy} title="Wildcard">
        <p>
          Applies when team monthly profit is greater than $100,000 USD and On time P&amp;D is
          at or above 95%. A 95% service result maps to the first bracket: 100 loads and{" "}
          {entryMarginLabel}
          margin. If the regular load bonus is lower, the wildcard minimum is respected.
        </p>
        <p className="text-[#64748B]">
          Wildcard is a <em>monthly</em> accomplishment; the regular bonuses are calculated
          weekly.
        </p>
      </RuleCard>

      <RuleCard Icon={CalendarRange} title="Period &amp; Data Cutoff">
        <ul className="ml-4 list-disc space-y-1.5">
          <li>
            The first week counted is the first full week of the month. The last week counted
            for that period is the last week of the month; if the last day of the month falls
            during the week, then the period is considered through the following Sunday.
          </li>
          <li>
            The data cutoff is on the 6th of the next month at 11:59 PM. Until then the current
            month keeps updating; afterwards it is frozen into the History tab.
          </li>
        </ul>
        <p className="mt-1 text-[11px] text-[#94A3B8]">
          Current report period: <span style={{ color: BRAND }}>{report.period.label}</span>
        </p>
      </RuleCard>

      {/* Bracket tables + role/wildcard cards + operating team structure. */}
      <CriteriaGuide report={report} />
    </div>
  )
}
