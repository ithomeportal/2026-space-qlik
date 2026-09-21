"use client"

import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useSpotsSummary,
  type SpotsFilters,
} from "@/lib/production-spots-trends-api"
import { Card, ErrorBlock, LoadingBlock } from "./Ui"

/** The headline row for the selected window.
 *
 *  Every tile's `title` carries the caveat that makes the number safe to quote.
 *  Win rate is the one to read carefully: it is Won / DECIDED, so quotes still
 *  in play are neither counted as losses nor silently dropped from the base.
 */
export function KpiCards({ filters }: { filters: SpotsFilters }) {
  const { data, error } = useSpotsSummary(filters)
  const d = data?.data
  const r = d?.range

  if (error) return <ErrorBlock what="the KPIs" error={error} />
  if (!r) return <LoadingBlock h={96} />

  const inPlayNote =
    r.in_play > 0
      ? `${fmtCount(r.in_play)} of ${fmtCount(r.quoted)} quotes still in play`
      : ""

  return (
    <div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Card
          label="Presented"
          value={fmtCount(r.presented)}
          sub={`${fmtCount(r.volume)} loads offered`}
          title="Every spot opportunity that reached us in this window — Home Depot offers plus lane-analysis consultations. Presented = Quoted + Skipped, exactly."
        />
        <Card
          label="Quoted"
          value={fmtCount(r.quoted)}
          sub={fmtPct(r.quote_rate) + " of presented"}
          title="We put a price on it (price is set and non-zero) — the quoting portal's Spot Desk definition. HD Spot uses buy_rate instead; the two differ on ~1.5% of Home Depot rows."
        />
        <Card
          label="Skipped"
          value={fmtCount(r.skipped)}
          sub={fmtPct(r.skip_rate) + " of presented"}
          tone={r.skip_rate !== null && r.skip_rate > 0.15 ? "warn" : "default"}
          title="Presented but never priced. ⚠ The REASON is not available in this data source: the skip-reason field has been empty since 2026-03-26 and the live taxonomy lives in a table this report cannot read."
        />
        <Card
          label="Won"
          value={fmtCount(r.won)}
          sub={`${fmtCount(r.loads_won)} loads`}
          tone="good"
          title="award_status = WON. Loads counts volume_awarded on Home Depot and the McLeod order numbers on the lane feed."
        />
        <Card
          label="Win rate"
          value={fmtPct(r.win_rate)}
          sub={`of ${fmtCount(r.decided)} decided`}
          title="Won / (Won + Lost + Rejected + No reply). Quotes still in play are excluded from the base rather than counted as losses. ⚠ On a recent window this is still settling — see the Trends tab's shaded tail."
        />
        <Card
          label="No reply"
          value={fmtCount(r.no_reply)}
          sub={fmtPct(r.no_reply_rate) + " of decided"}
          tone={r.no_reply_rate !== null && r.no_reply_rate > 0.25 ? "warn" : "default"}
          title="Quotes the customer never answered — aged off automatically after 30 days (award_status 'LOST-A'). Distinct from an explicit rejection, and usually the biggest single leak."
        />
        <Card
          label="Awarded revenue"
          value={fmtUsd(r.awarded_revenue)}
          sub={`avg ${fmtUsd(r.avg_award_price)} / award`}
          title="Sum of the quoted price on won rows. This is what we WON, not what has been billed — the Moved (Actuals) tab carries what McLeod says actually departed."
        />
        <Card
          label="Awarded margin"
          value={fmtPct(r.awarded_margin)}
          sub={
            r.awarded_profit_n < r.won
              ? `on ${fmtCount(r.awarded_profit_n)} of ${fmtCount(r.won)} wins`
              : ""
          }
          title="(price − accessorials − buy rate) ÷ price, computed only on won rows where BOTH legs are known, and divided by the revenue of those same rows. The sub-line names the coverage when it is partial."
        />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-[#6B7280]">
        <span>
          Potential revenue quoted <strong>{fmtUsd(r.potential_revenue)}</strong>
        </span>
        <span>
          Rejected <strong>{fmtCount(r.rejected + r.lost)}</strong> ·
          Cancelled <strong>{fmtCount(r.cancelled)}</strong>
        </span>
        {inPlayNote ? <span>{inPlayNote}</span> : null}
        {d?.range_window?.covers_outage ? (
          <span className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[#92400E]">
            ⚠ This window spans 17–20 Jul 2026, when the feed was frozen for three
            days — those days are partial
          </span>
        ) : null}
      </div>
    </div>
  )
}
