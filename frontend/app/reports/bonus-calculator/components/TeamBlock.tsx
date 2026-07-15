"use client"

import { useState } from "react"
import { ChevronDown, Minus, Plus, Sparkles } from "lucide-react"
import type { BonusReport, BonusTeam, BonusEmployee } from "@/lib/bonus-api"
import { COLORS, usd, usd0, pct, num, ROLE_LABEL } from "../format"

// Bruno Bonus R4 (PDF 2026-07-15): the "Actual Data" / "Actual Bonus %" tables
// and the payout (Team) table must share the SAME week-column geometry so the
// week columns line up vertically. A single shared <colgroup> (identical fixed
// widths) + table-fixed + a matching min-width on both tables guarantees the
// columns align; both tables live in ONE horizontal-scroll wrapper so scrolling
// stays in sync. The Actual Data table simply leaves the trailing (non-week)
// columns empty.
const COL = {
  label: 180,
  week: 110,
  usdTotal: 96,
  wildcard: 116,
  kam: 124,
  bracket: 56,
  total: 96,
}

function AlignedColGroup({ weeks }: { weeks: number }) {
  return (
    <colgroup>
      <col style={{ width: COL.label }} />
      {Array.from({ length: weeks }, (_, i) => (
        <col key={i} style={{ width: COL.week }} />
      ))}
      <col style={{ width: COL.usdTotal }} />
      <col style={{ width: COL.wildcard }} />
      <col style={{ width: COL.kam }} />
      <col style={{ width: COL.bracket }} />
      <col style={{ width: COL.bracket }} />
      <col style={{ width: COL.bracket }} />
      <col style={{ width: COL.total }} />
    </colgroup>
  )
}

function alignedMinWidth(weeks: number): number {
  return (
    COL.label +
    weeks * COL.week +
    COL.usdTotal +
    COL.wildcard +
    COL.kam +
    3 * COL.bracket +
    COL.total
  )
}

function MiniKpi({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="text-right">
      <p className="text-[9px] font-bold uppercase tracking-wider text-[#94A3B8]">{label}</p>
      <p className="text-sm font-bold" style={{ color: accent || "#1F2937" }}>
        {value}
      </p>
    </div>
  )
}

function WildcardPanel({ team }: { team: BonusTeam }) {
  // One representative employee per role gives the weekly wildcard math.
  const byRole = (role: string) => team.employees.find((e) => e.role === role)
  const rows = (["kam", "freight_match", "tracking_tracing"] as const)
    .map((role) => ({ role, emp: byRole(role) }))
    .filter((r) => r.emp) as { role: string; emp: BonusEmployee }[]

  return (
    <div className="rounded-xl border p-4" style={{ background: COLORS.wildcardBg, borderColor: "#A7F3D0" }}>
      <div className="overflow-hidden rounded-lg border" style={{ borderColor: "#A7F3D0" }}>
        <div className="grid grid-cols-[1fr_2fr_auto] px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-white" style={{ background: COLORS.wildcardTitle }}>
          <span>Role</span>
          <span>Weekly wildcard calculation</span>
          <span className="text-right">Weekly wildcard to pay</span>
        </div>
        {rows.map(({ role, emp }) => (
          <div key={role} className="grid grid-cols-[1fr_2fr_auto] items-center border-t border-[#D1FAE5] bg-white px-3 py-2 text-xs">
            <div>
              <p className="font-semibold text-[#0F172A]">
                {ROLE_LABEL[role]} · {role === "kam" ? "Load Count" : role === "freight_match" ? "Margin" : "Service"}
              </p>
              <p className="text-[11px] text-[#64748B]">{emp.name}</p>
            </div>
            <p className="text-[#475569]">
              {team.wildcardEquivalentLoads.toFixed(1)} loads × {Math.round(emp.wildcardRoleBonusPct * 100)}% ×{" "}
              {usd(emp.wildcardBasePayUsd)} per load, calculated per week
            </p>
            <p className="text-right font-bold" style={{ color: COLORS.wildcardTitle }}>
              {usd(emp.wildcardWeeklyUsd)}
            </p>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-[#64748B]">
        Wildcard uses the service bracket to create a weekly payout by role. These amounts are weekly wildcard
        calculations, not monthly total bonus amounts.
      </p>
    </div>
  )
}

function ActualDataTable({ team }: { team: BonusTeam }) {
  const weeks = team.weeklyRules
  const blue = COLORS.blueHeader
  // Bruno R4: full column count = label + N weeks + 7 trailing (USD Total,
  // Wildcard, KAM Bonus, 130, 150, 170, Total). The "Actual Bonus %" banner
  // spans all of them so it reads full-width like the mock.
  const totalCols = weeks.length + 8
  return (
    <div className="rounded-lg border border-[#E5E7EB]">
      <table className="w-full table-fixed text-xs" style={{ minWidth: alignedMinWidth(weeks.length) }}>
        <AlignedColGroup weeks={weeks.length} />
        <thead>
          <tr style={{ background: blue }} className="text-white">
            <th className="px-3 py-2 text-left font-semibold">Actual Data</th>
            {weeks.map((w, i) => (
              <th key={i} className="px-3 py-2 text-center font-semibold">
                {`Week ${i + 1}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="border-t border-[#EEF2F7]">
            <td className="px-3 py-1.5 font-medium text-[#475569]">Load Count</td>
            {weeks.map((w, i) => (
              <td key={i} className="px-3 py-1.5 text-center text-[#1F2937]">{num(w.loads)}</td>
            ))}
          </tr>
          <tr className="border-t border-[#EEF2F7]">
            <td className="px-3 py-1.5 font-medium text-[#475569]">Margin %</td>
            {weeks.map((w, i) => (
              <td key={i} className="px-3 py-1.5 text-center text-[#1F2937]">{pct(w.marginPct * 100)}</td>
            ))}
          </tr>
          <tr className="border-t border-[#EEF2F7]">
            <td className="px-3 py-1.5 font-medium text-[#475569]">On time P&amp;D</td>
            {weeks.map((w, i) => (
              <td key={i} className="px-3 py-1.5 text-center text-[#1F2937]">{pct(w.serviceAveragePct)}</td>
            ))}
          </tr>
        </tbody>
        <thead>
          <tr style={{ background: blue }} className="text-white">
            <th className="px-3 py-1.5 text-left font-semibold" colSpan={totalCols}>
              Actual Bonus %
            </th>
          </tr>
        </thead>
        <tbody style={{ background: COLORS.greenRow }}>
          <tr>
            <td className="px-3 py-1.5 font-medium text-[#1F2937]">Load Count</td>
            {weeks.map((w, i) => (
              <td key={i} className="px-3 py-1.5 text-center font-semibold text-[#1F2937]">{pct(w.loadBonusPct * 100)}</td>
            ))}
          </tr>
          <tr className="border-t border-[#BEF264]">
            <td className="px-3 py-1.5 font-medium text-[#1F2937]">Margin %</td>
            {weeks.map((w, i) => (
              <td key={i} className="px-3 py-1.5 text-center font-semibold text-[#1F2937]">{pct(w.marginBonusPct * 100)}</td>
            ))}
          </tr>
          <tr className="border-t border-[#BEF264]">
            <td className="px-3 py-1.5 font-medium text-[#1F2937]">On time P&amp;D</td>
            {weeks.map((w, i) => (
              <td key={i} className="px-3 py-1.5 text-center font-semibold text-[#1F2937]">{pct(w.serviceBonusPctWeekly * 100)}</td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  )
}

// Bruno Bonus R3 (2026-07-15): the 130/150/170 profit brackets carry a "k"
// suffix (they are $-thousands thresholds).
function BracketHeader({ value }: { value: string }) {
  return (
    <>
      {value}
      <span className="text-[9px] font-normal">k</span>
    </>
  )
}

function PayoutTable({ team, weekLabels }: { team: BonusTeam; weekLabels: string[] }) {
  const blue = COLORS.blueHeader
  return (
    <div className="rounded-lg border border-[#E5E7EB]">
      <table className="w-full table-fixed text-xs" style={{ minWidth: alignedMinWidth(weekLabels.length) }}>
        <AlignedColGroup weeks={weekLabels.length} />
        <thead>
          {/* Bruno Bonus R2 (2026-07-15): "Bracket Bonus" group title above the
              130/150/170 columns. */}
          <tr>
            <th colSpan={weekLabels.length + 4} />
            <th
              colSpan={3}
              className="px-2 py-1 text-center text-[10px] font-bold uppercase tracking-wider text-white"
              style={{ background: blue }}
            >
              Bracket Bonus
            </th>
            <th />
          </tr>
          <tr style={{ background: blue }} className="text-white">
            <th className="px-3 py-2 text-left font-semibold">{team.name}</th>
            {weekLabels.map((l, i) => (
              <th key={i} className="px-2 py-2 text-center font-semibold">{l}</th>
            ))}
            <th className="px-2 py-2 text-center font-semibold">USD Total</th>
            <th className="px-2 py-2 text-center font-semibold">Wildcard</th>
            <th className="px-2 py-2 text-center font-semibold">KAM Bonus</th>
            <th className="px-2 py-2 text-center font-semibold"><BracketHeader value="130" /></th>
            <th className="px-2 py-2 text-center font-semibold"><BracketHeader value="150" /></th>
            <th className="px-2 py-2 text-center font-semibold"><BracketHeader value="170" /></th>
            <th className="px-2 py-2 text-center font-semibold" style={{ background: COLORS.greenRow, color: "#1F2937" }}>
              Total
            </th>
          </tr>
        </thead>
        <tbody>
          {team.employees.map((e, idx) => {
            const bracket = (label: string) => e.profitBracketBonuses.find((b) => b.label.startsWith(label))?.payoutUsd ?? 0
            const wildcardActive = e.wildcardAppliedUsd > 0
            return (
              <tr key={idx} className="border-t border-[#EEF2F7]">
                <td className="px-3 py-2 font-semibold uppercase text-[#1F2937]">{e.name}</td>
                {e.weeklyUsd.map((v, i) => (
                  <td key={i} className="px-2 py-2 text-center text-[#334155]">{usd(v)}</td>
                ))}
                <td className="px-2 py-2 text-center font-semibold text-[#1F2937]">{usd(e.bonusUsd)}</td>
                {/* Bruno R8 (2026-06-03): show ONLY the weekly wildcard payment
                    amount here (e.g. $160.00), matching the Weekly Wildcard To
                    Pay panel — not the monthly total (weekly × #weeks). */}
                <td className="px-2 py-2 text-center text-[#334155]">
                  {e.wildcardBonusUsd > 0 ? (
                    <div>
                      <span className="font-semibold">{usd(e.wildcardWeeklyUsd)}</span>
                      {wildcardActive && (
                        <span className="block text-[9px] font-bold uppercase tracking-wider" style={{ color: COLORS.wildcardTitle }}>
                          weekly minimum
                        </span>
                      )}
                    </div>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-2 py-2 text-center text-[#334155]">
                  {e.kamBonusUsd > 0 ? (
                    <div>
                      <span className="font-semibold">{usd(e.kamBonusUsd)}</span>
                      {e.kamBonusMxn > 0 && (
                        <span className="block text-[9px] text-[#7C3AED]">
                          ${num(e.kamBonusMxn)} MXN · DOF {e.kamBonusFxRate.toFixed(2)}
                        </span>
                      )}
                    </div>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-2 py-2 text-center text-[#334155]">{bracket("130") ? usd0(bracket("130")) : "—"}</td>
                <td className="px-2 py-2 text-center text-[#334155]">{bracket("150") ? usd0(bracket("150")) : "—"}</td>
                <td className="px-2 py-2 text-center text-[#334155]">{bracket("170") ? usd0(bracket("170")) : "—"}</td>
                <td className="px-2 py-2 text-center font-bold text-[#1F2937]" style={{ background: COLORS.greenRow }}>
                  {usd(e.totalBonusUsd)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function TeamBlock({ team, report }: { team: BonusTeam; report: BonusReport }) {
  const [showWildcard, setShowWildcard] = useState(false)
  // Bruno Bonus R5 (2026-07-15): collapse/expand each team container.
  const [collapsed, setCollapsed] = useState(false)
  // Bruno Bonus R1 (2026-07-15): team bonus total KPI — the sum of the payout
  // table's "Total" column, so the KPI reconciles exactly with the detail rows.
  const teamTotalBonus = team.employees.reduce((s, e) => s + (e.totalBonusUsd || 0), 0)
  return (
    <section className="rounded-2xl border border-[#EDE9FE] bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-xl bg-[#F5F3FF] p-4">
        <div>
          <h3 className="text-lg font-bold text-[#1F2937]">{team.name}</h3>
          <p className="text-xs text-[#6B7280]">
            Weekly Load Count and Margin %, monthly On time P&amp;D, wildcard eligibility, and the actual USD payout by
            employee including achieved monthly profit brackets.
          </p>
        </div>
        {/* Bruno 2026-05-28: KPIs are the calendar-month cumulative (1st→last
            day), not the sum of the weekly buckets below. */}
        <div className="flex items-start gap-4">
          <div className="flex flex-wrap gap-5">
            <MiniKpi label="Loads" value={num(team.monthlyLoads)} />
            <MiniKpi label="Profit" value={usd0(team.monthlyProfit)} />
            <MiniKpi label="Margin" value={pct(team.monthlyMarginPct * 100, 1)} />
            <MiniKpi label="Service" value={pct(team.monthlyServicePct, 2)} />
            <MiniKpi
              label="Wildcard"
              value={team.wildcardEligible ? "Eligible" : "—"}
              accent={team.wildcardEligible ? COLORS.wildcardTitle : "#94A3B8"}
            />
            <MiniKpi label="Bonus" value={usd0(teamTotalBonus)} accent={COLORS.blueHeader} />
          </div>
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-label={collapsed ? "Expand team" : "Collapse team"}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-white shadow-sm"
            style={{ background: COLORS.blueHeader }}
          >
            {collapsed ? <Plus className="h-4 w-4" /> : <Minus className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {!collapsed && (
        <>
          {team.wildcardEligible && (
            <div className="mt-4">
              <button
                onClick={() => setShowWildcard((v) => !v)}
                className="flex w-full items-center justify-between rounded-lg border px-4 py-2.5 text-sm font-semibold"
                style={{ background: COLORS.wildcardBg, borderColor: "#A7F3D0", color: COLORS.wildcardTitle }}
              >
                <span className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4" />
                  Wildcard eligible — view weekly wildcard calculation
                </span>
                <ChevronDown className={`h-4 w-4 transition-transform ${showWildcard ? "rotate-180" : ""}`} />
              </button>
              {showWildcard && (
                <div className="mt-3">
                  <WildcardPanel team={team} />
                </div>
              )}
            </div>
          )}

          {/* Bruno R4 (2026-07-15): both tables share one horizontal-scroll
              wrapper + the same colgroup so their week columns stay aligned. */}
          <div className="mt-4 space-y-3 overflow-x-auto">
            <ActualDataTable team={team} />
            <p className="text-[11px] text-[#94A3B8]">
              The green rows show what each result represents in the bonus bracket — the bonus percentage earned that week.
            </p>
            <PayoutTable team={team} weekLabels={report.period.weekLabels} />
          </div>
        </>
      )}
    </section>
  )
}
