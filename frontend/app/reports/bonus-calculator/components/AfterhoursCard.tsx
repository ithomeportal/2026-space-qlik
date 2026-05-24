import { MoonStar } from "lucide-react"
import type { BonusReport } from "@/lib/bonus-api"
import { COLORS, usd } from "../format"

export function AfterhoursCard({ report }: { report: BonusReport }) {
  const ns = report.nightShift
  const perPerson = ns.trackingTracingAverageBonusUsd
  return (
    <section className="rounded-2xl border border-[#EDE9FE] bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2">
        <MoonStar className="h-5 w-5" style={{ color: COLORS.cardTitle }} />
        <h2 className="text-lg font-bold text-[#1F2937]">T&amp;T, Night and Weekend Bonus</h2>
      </div>
      <p className="mt-1 text-xs text-[#6B7280]">
        Each eligible Afterhours member receives the average of the Tracking &amp; Tracing weekly bonus across the 4 day
        teams (third-level profit bracket excluded).
      </p>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl p-4" style={{ background: COLORS.cardBg }}>
          <p className="text-[11px] font-bold uppercase tracking-wider" style={{ color: COLORS.cardTitle }}>
            Formula
          </p>
          <p className="mt-1 text-xs text-[#475569]">Average of T&amp;T weekly bonus across 4 teams</p>
          <p className="mt-2 text-2xl font-bold text-[#1F2937]">{usd(perPerson)} <span className="text-sm font-medium text-[#6B7280]">per eligible person</span></p>
          <p className="mt-1 text-[11px] text-[#94A3B8]">
            The system keeps the weekly Tracking &amp; Tracing average calculation behind the scenes and shows only the
            final payout amount for easier HR review.
          </p>
        </div>

        <div className="rounded-xl border p-4" style={{ background: COLORS.wildcardBg, borderColor: "#A7F3D0" }}>
          <p className="text-[11px] font-bold uppercase tracking-wider" style={{ color: COLORS.wildcardTitle }}>
            Team T&amp;T Contributions
          </p>
          <div className="mt-2 space-y-1.5">
            {ns.trackingTracingTeamBonuses.map((t) => (
              <div key={t.teamName} className="flex items-center justify-between rounded-md bg-white px-3 py-1.5 text-xs">
                <span className="font-semibold text-[#1F2937]">{t.teamName}</span>
                <span className="font-bold" style={{ color: COLORS.wildcardTitle }}>{usd(t.bonusUsd)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {ns.employees.length > 0 && (
        <div className="mt-4 overflow-x-auto rounded-lg border border-[#E5E7EB]">
          <table className="w-full min-w-[480px] text-xs">
            <thead>
              <tr className="bg-[#F8FAFC] text-[#475569]">
                <th className="px-3 py-2 text-left font-semibold">Afterhours member</th>
                <th className="px-3 py-2 text-left font-semibold">Group</th>
                <th className="px-3 py-2 text-center font-semibold">Eligible</th>
                <th className="px-3 py-2 text-right font-semibold">Bonus (USD)</th>
              </tr>
            </thead>
            <tbody>
              {ns.employees.map((e, i) => (
                <tr key={i} className="border-t border-[#EEF2F7]">
                  <td className="px-3 py-1.5 font-medium text-[#1F2937]">{e.name}</td>
                  <td className="px-3 py-1.5 text-[#6B7280]">{e.group}</td>
                  <td className="px-3 py-1.5 text-center">{e.receivesBonus ? "Yes" : "No"}</td>
                  <td className="px-3 py-1.5 text-right font-semibold text-[#1F2937]">{usd(e.bonusUsd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
