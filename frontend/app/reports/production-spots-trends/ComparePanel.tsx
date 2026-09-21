"use client"

import {
  fmtCount,
  fmtPct,
  fmtRange,
  fmtUsdShort,
  useSpotsSummary,
  type SpotsBucket,
  type SpotsCompare,
  type SpotsFilters,
  type SpotsSummary,
} from "@/lib/production-spots-trends-api"
import { DeltaChip, ErrorBlock, Footnote, LoadingBlock, Panel, TD, TH } from "./Ui"

/** The three comparative blocks — the reason this report exists.
 *
 *  Two different alignments, on purpose:
 *
 *  * ACTIVITY (presented / quoted / skipped) compares the raw aligned windows.
 *    Week-to-date runs against the same WEEKDAYS last week and month-to-date
 *    against the same elapsed BUSINESS DAYS last month, because Wednesday
 *    carries half again as much volume as Friday and the weekend is empty.
 *  * OUTCOMES (win rate, awarded revenue) compare the last SETTLED periods.
 *    Home Depot's "priced, pending" state resolves on day 7–10 and the lane
 *    feed settles at the 30-day age-off, so this week against last week would
 *    pit a 2-day-old cohort against a 9-day-old one and the older one would win
 *    every single time.
 */

type Row = {
  key: keyof SpotsBucket
  label: string
  fmt: (n: number | null | undefined) => string
  /** true when DOWN is the good direction (skip rate, no-reply rate) */
  goodDown?: boolean
  /** a rate's own change reads as points, not a percentage of a percentage */
  asPct?: boolean
  title?: string
}

const ACTIVITY: Row[] = [
  { key: "presented", label: "Presented", fmt: fmtCount },
  { key: "quoted", label: "Quoted", fmt: fmtCount },
  { key: "skipped", label: "Skipped", fmt: fmtCount, goodDown: true },
  { key: "quote_rate", label: "Quote rate", fmt: fmtPct, asPct: true },
  { key: "potential_revenue", label: "Potential rev.", fmt: fmtUsdShort },
]

const OUTCOME: Row[] = [
  { key: "won", label: "Won", fmt: fmtCount },
  { key: "win_rate", label: "Win rate", fmt: fmtPct, asPct: true },
  {
    key: "no_reply_rate",
    label: "No reply",
    fmt: fmtPct,
    asPct: true,
    goodDown: true,
  },
  { key: "awarded_revenue", label: "Awarded rev.", fmt: fmtUsdShort },
  { key: "awarded_margin", label: "Margin", fmt: fmtPct, asPct: true },
]

function CompareTable({
  block,
  rows,
  currentLabel,
  previousLabel,
}: {
  block: SpotsCompare
  rows: Row[]
  currentLabel: string
  previousLabel: string
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-0 text-xs">
        <thead className="bg-[#F3F4F6] text-[#374151]">
          <tr>
            <th className={`${TH} text-left`}>Metric</th>
            <th className={`${TH} text-right`}>{currentLabel}</th>
            <th className={`${TH} text-right`}>{previousLabel}</th>
            <th className={`${TH} text-right`}>Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={String(r.key)} className={i % 2 ? "bg-[#FAFAFA]" : "bg-white"}>
              <td className="whitespace-nowrap px-2 py-1 text-left" title={r.title}>
                {r.label}
              </td>
              <td className={`${TD} font-semibold text-[#1B3A5C]`}>
                {r.fmt(block.current[r.key] as number | null)}
              </td>
              <td className={`${TD} text-[#6B7280]`}>
                {r.fmt(block.previous[r.key] as number | null)}
              </td>
              <td className={TD}>
                <DeltaChip
                  delta={block.deltas[String(r.key)]}
                  goodDown={r.goodDown}
                  asPct={r.asPct}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Block({
  title,
  subtitle,
  block,
  rows,
  currentLabel,
  previousLabel,
  footnote,
}: {
  title: string
  subtitle: string
  block: SpotsCompare
  rows: Row[]
  currentLabel: string
  previousLabel: string
  footnote?: string
}) {
  return (
    <Panel title={title} subtitle={subtitle}>
      <CompareTable
        block={block}
        rows={rows}
        currentLabel={currentLabel}
        previousLabel={previousLabel}
      />
      <Footnote>
        {currentLabel} {fmtRange(block.window)} ({block.window.business_days} business
        days) vs {previousLabel} {fmtRange(block.previous_window)} (
        {block.previous_window.business_days} business days).
        {footnote ? ` ${footnote}` : ""}
      </Footnote>
    </Panel>
  )
}

function Projection({ d }: { d: SpotsSummary }) {
  const p = d.projection
  const legs: { key: string; label: string; fmt: (n: number | null) => string }[] = [
    { key: "presented", label: "Presented", fmt: fmtCount },
    { key: "quoted", label: "Quoted", fmt: fmtCount },
    { key: "won", label: "Won", fmt: fmtCount },
    { key: "awarded_revenue", label: "Awarded revenue", fmt: fmtUsdShort },
  ]
  return (
    <Panel
      title="Month-end projection"
      subtitle={`${p.business_days_elapsed} of ${p.business_days_total} business days elapsed · ${fmtPct(p.pace, 0)} through the month`}
    >
      <div className="overflow-x-auto">
        <table className="w-full border-separate border-spacing-0 text-xs">
          <thead className="bg-[#F3F4F6] text-[#374151]">
            <tr>
              <th className={`${TH} text-left`}>Metric</th>
              <th className={`${TH} text-right`}>Month to date</th>
              <th className={`${TH} text-right`}>Projected month end</th>
              <th className={`${TH} text-right`}>Last month (full)</th>
              <th className={`${TH} text-right`}>Projected vs last</th>
            </tr>
          </thead>
          <tbody>
            {legs.map((leg, i) => {
              const v = p[leg.key]
              if (!v || typeof v !== "object" || !("mtd" in v)) return null
              return (
                <tr key={leg.key} className={i % 2 ? "bg-[#FAFAFA]" : "bg-white"}>
                  <td className="whitespace-nowrap px-2 py-1 text-left">{leg.label}</td>
                  <td className={`${TD} text-[#6B7280]`}>{leg.fmt(v.mtd)}</td>
                  <td className={`${TD} font-semibold text-[#1B3A5C]`}>
                    {leg.fmt(v.projected)}
                  </td>
                  <td className={`${TD} text-[#6B7280]`}>{leg.fmt(v.last_month)}</td>
                  <td className={TD}>
                    <DeltaChip delta={v.vs_last_month} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <Footnote>
        Run rate = month-to-date ÷ business days elapsed, extended over the month&apos;s{" "}
        {p.business_days_total} business days. <strong>Mon–Fri</strong>, because Home
        Depot posts no offers at weekends at all and the lane feed only a trickle — a
        calendar-day divisor would understate every projection by about a sixth. Last
        month had {p.business_days_last_month} business days, so compare the rate, not
        only the total. ⚠ Projected <em>Won</em> inherits the settling problem: this
        month&apos;s recent wins are not all recorded yet, so it runs low.
      </Footnote>
    </Panel>
  )
}

export function ComparePanel({ filters }: { filters: SpotsFilters }) {
  const { data, error } = useSpotsSummary(filters)
  const d = data?.data

  if (error) return <ErrorBlock what="the comparatives" error={error} />
  if (!d) return <LoadingBlock h={240} />

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Block
          title="This week vs last week"
          subtitle="same weekdays, to the same point"
          block={d.week}
          rows={ACTIVITY}
          currentLabel="WTD"
          previousLabel="Last week"
        />
        <Block
          title="This month vs last month"
          subtitle="same elapsed business days"
          block={d.month}
          rows={ACTIVITY}
          currentLabel="MTD"
          previousLabel="Last month"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Block
          title="Outcomes — last settled week"
          subtitle={`quotes older than ${d.maturity_days} days`}
          block={d.settled_week}
          rows={OUTCOME}
          currentLabel="Settled week"
          previousLabel="Week before"
          footnote={`Settled periods only. Home Depot quotes resolve ${d.hd_maturity_days} days out and lane quotes age off at ${d.maturity_days}, so a fresher week would show a lower win rate for that reason alone.`}
        />
        <Block
          title="Outcomes — last settled month"
          subtitle={`quotes older than ${d.maturity_days} days`}
          block={d.settled_month}
          rows={OUTCOME}
          currentLabel="Settled month"
          previousLabel="Month before"
        />
      </div>

      <Projection d={d} />
    </div>
  )
}
