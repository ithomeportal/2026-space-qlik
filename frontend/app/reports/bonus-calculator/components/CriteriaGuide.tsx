import { SlidersHorizontal } from "lucide-react"
import type { BonusReport, Bracket } from "@/lib/bonus-api"
import { COLORS, usd } from "../format"

function BracketTable({
  title,
  headerBg,
  brackets,
  fmtThreshold,
  baseLabel,
}: {
  title: string
  headerBg: string
  brackets: Bracket[]
  fmtThreshold: (t: number) => string
  baseLabel: string
}) {
  const dark = headerBg === COLORS.loadHeader
  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB]">
      <div className="px-3 py-2 text-center text-xs font-bold uppercase tracking-wider" style={{ background: headerBg, color: dark ? "#fff" : "#1F2937" }}>
        {title}
      </div>
      <div className="bg-[#F8FAFC] px-3 py-1.5 text-center text-[11px] font-semibold text-[#475569]">Bonus %</div>
      <table className="w-full text-center text-xs">
        <tbody>
          {brackets.map((b, i) => (
            <tr key={i} className="border-t border-[#EEF2F7]">
              <td className="w-1/2 px-2 py-1.5 text-[#334155]">{fmtThreshold(b.threshold)}</td>
              <td className="w-1/2 px-2 py-1.5 font-bold text-[#0F172A]">{Math.round(b.bonusPct * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-3 py-1.5 text-center text-[11px] font-bold text-[#1F2937]" style={{ background: COLORS.greenRow }}>
        {baseLabel}
      </div>
    </div>
  )
}

function InfoCard({ title, body, bg, titleColor }: { title: string; body: string; bg: string; titleColor: string }) {
  return (
    <div className="rounded-xl p-4" style={{ background: bg }}>
      <p className="text-[11px] font-bold uppercase tracking-wider" style={{ color: titleColor }}>
        {title}
      </p>
      <p className="mt-2 text-xs leading-relaxed text-[#475569]">{body}</p>
    </div>
  )
}

const TEAM_STRUCTURE = [
  { team: "Team 1", detail: "1 KAM · 1 Freight Match · 1 Tracking & Tracing" },
  { team: "Team 2", detail: "1 KAM · 1 Freight Match · 1 Tracking & Tracing" },
  { team: "Team 3", detail: "1 KAM · 1 Freight Match · 2 Tracking & Tracing" },
  { team: "Team 4", detail: "1 KAM · 0 Freight Match · 1 Tracking & Tracing" },
]

export function CriteriaGuide({ report }: { report: BonusReport }) {
  const { loadCountBrackets, marginBrackets, serviceBrackets, payPerLoad } = report.criteria
  // ⚠ The entry margin is 18.5% corporate but 15.0% on DFW (Bruno PDF
  // 2026-08-20). Read it off the ladder the server sent rather than typing it:
  // prose that contradicts the table right above it is worse than no prose.
  const entryMarginLabel = marginBrackets?.length
    ? `${(marginBrackets[0].threshold * 100).toFixed(1)}%`
    : "the entry"
  return (
    <section className="rounded-2xl border border-[#EDE9FE] bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2">
        <SlidersHorizontal className="h-5 w-5" style={{ color: COLORS.cardTitle }} />
        <h2 className="text-lg font-bold text-[#1F2937]">Bonus Criteria Guide</h2>
      </div>
      <p className="mt-1 text-xs text-[#6B7280]">
        Use this table first. Every role must first reach a minimum of 100 loads in the week — below that no bonus
        applies, even if margin or service clear their bracket. KAMs then qualify by load count, Freight Match by
        margin percentage, and Tracking &amp; Tracing by the current-month average of pickup and delivery service.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        <BracketTable
          title="Load Count Bracket"
          headerBg={COLORS.loadHeader}
          brackets={loadCountBrackets}
          fmtThreshold={(t) => t.toFixed(1)}
          baseLabel={`Base payout per load: ${usd(payPerLoad.kam)}`}
        />
        <BracketTable
          title="Margin Bracket"
          headerBg={COLORS.marginHeader}
          brackets={marginBrackets}
          fmtThreshold={(t) => `${(t * 100).toFixed(1)}%`}
          baseLabel={`Base payout per load: ${usd(payPerLoad.freight_match)}`}
        />
        <BracketTable
          title="Service Bracket"
          headerBg={COLORS.serviceHeader}
          brackets={serviceBrackets}
          fmtThreshold={(t) => `${Math.round(t * 100)}%`}
          baseLabel={`Base payout per load: ${usd(payPerLoad.tracking_tracing)}`}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <InfoCard title="KAM Load Count" body="KAM has one requirement: reach a minimum of 100 loads in the week, then the load-count bracket sets the bonus." bg={COLORS.cardBg} titleColor={COLORS.cardTitle} />
        <InfoCard
          title="Freight Match Margin"
          body={`Freight Match needs a minimum of 100 loads in the week and an ${entryMarginLabel} margin; the margin bracket pays only once the 100-load minimum is met. Wildcard is the only alternate payout path.`}
          bg={COLORS.cardBg}
          titleColor={COLORS.cardTitle}
        />
        <InfoCard
          title="Tracking & Tracing Service"
          body="Tracking & Tracing needs a minimum of 100 loads in the week plus the current-month pickup and delivery service average; below 100 loads no service bonus applies that week."
          bg={COLORS.cardBg}
          titleColor={COLORS.cardTitle}
        />
        <InfoCard
          title="Wildcard"
          body={`Wildcard applies when team monthly profit is greater than $100,000 USD and On time P&D is at or above 95%. A 95% service result maps to the first bracket: 100 loads and ${entryMarginLabel} margin. If the regular load bonus is lower, the wildcard minimum is respected.`}
          bg={COLORS.wildcardBg}
          titleColor={COLORS.wildcardTitle}
        />
      </div>

      <div className="mt-4 rounded-xl border border-[#E5E7EB] bg-[#FAFAFC] p-4">
        <p className="text-[11px] font-bold uppercase tracking-wider text-[#6B7280]">Operating Team Structure</p>
        <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {TEAM_STRUCTURE.map((t) => (
            <div key={t.team} className="rounded-lg border border-[#E5E7EB] bg-white p-3">
              <p className="text-sm font-bold text-[#1F2937]">{t.team}</p>
              <p className="mt-1 text-[11px] text-[#6B7280]">{t.detail}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
