"use client"

import {
  fmtCount,
  fmtPct,
  fmtUsdShort,
  useSpotsSummary,
  type SpotsBucket,
  type SpotsFilters,
} from "@/lib/production-spots-trends-api"
import { ErrorBlock, Footnote, LoadingBlock, Panel } from "./Ui"

/** The funnel, as a set of proportional bars.
 *
 *  The stages PARTITION the population — Presented = Quoted + Skipped, and
 *  Quoted = Won + Lost + Rejected + No reply + Cancelled + In play + Other —
 *  so the bars add up and a reader can check them. That is enforced by a test
 *  against the live table, not just by intent.
 */

type Stage = {
  key: keyof SpotsBucket
  label: string
  colour: string
  of: "presented" | "quoted"
  title: string
}

const STAGES: Stage[] = [
  {
    key: "won",
    label: "Won",
    colour: "#047857",
    of: "quoted",
    title: "award_status = WON — the quote became an award.",
  },
  {
    key: "lost",
    label: "Lost",
    colour: "#B91C1C",
    of: "quoted",
    title:
      "An explicit loss: the customer priced elsewhere. LOST / DECLINED / CLOSE AUTO.",
  },
  {
    key: "rejected",
    label: "Rejected",
    colour: "#DC2626",
    of: "quoted",
    title:
      "Home Depot only, and always recorded by hand — an outright rejection rather than a quiet loss. Only a few dozen rows exist, so treat it as a flag, not a trend.",
  },
  {
    key: "no_reply",
    label: "No reply",
    colour: "#D97706",
    of: "quoted",
    title:
      "The customer never came back. A cron ages an unanswered quote off after 30 days (LOST-A). This is the leak that an ordinary win/loss split hides inside 'Lost'.",
  },
  {
    key: "in_play",
    label: "In play",
    colour: "#2563EB",
    of: "quoted",
    title:
      "Still open, or priced with the outcome pending. These are NOT losses — they are excluded from the win-rate base rather than counted against it.",
  },
  {
    key: "cancelled",
    label: "Cancelled",
    colour: "#6B7280",
    of: "quoted",
    title: "The quote was voided (CANCELED).",
  },
  {
    key: "other_outcome",
    label: "Other",
    colour: "#9CA3AF",
    of: "quoted",
    title:
      "A status outside the known set. Normally zero — it exists so a new status the feed invents lands somewhere visible instead of falling out of the total.",
  },
]

function Bar({
  label,
  value,
  base,
  colour,
  title,
  strong = false,
}: {
  label: string
  value: number
  base: number
  colour: string
  title: string
  strong?: boolean
}) {
  const pct = base > 0 ? value / base : 0
  return (
    <div className="flex items-center gap-3" title={title}>
      <div
        className={`w-28 shrink-0 text-[11px] ${
          strong ? "font-semibold text-[#1B3A5C]" : "text-[#374151]"
        }`}
      >
        {label}
      </div>
      <div className="h-5 min-w-0 flex-1 overflow-hidden rounded bg-[#F3F4F6]">
        <div
          className="h-full rounded"
          style={{
            width: `${Math.max(pct * 100, value > 0 ? 0.6 : 0)}%`,
            backgroundColor: colour,
          }}
        />
      </div>
      <div className="w-20 shrink-0 text-right text-[11px] font-semibold tabular-nums text-[#111827]">
        {fmtCount(value)}
      </div>
      <div className="w-14 shrink-0 text-right text-[10px] tabular-nums text-[#6B7280]">
        {fmtPct(pct, 1)}
      </div>
    </div>
  )
}

export function FunnelPanel({ filters }: { filters: SpotsFilters }) {
  const { data, error } = useSpotsSummary(filters)
  const r = data?.data?.range

  if (error) return <ErrorBlock what="the funnel" error={error} />
  if (!r) return <LoadingBlock h={260} />

  const sumOutcomes = STAGES.filter((s) => s.key !== "in_play").reduce(
    (acc, s) => acc + (r[s.key] as number),
    0
  )
  const reconciles = Math.abs(sumOutcomes + r.in_play - r.quoted) < 0.5

  return (
    <Panel
      title="The funnel"
      subtitle="every stage as a share of its own parent"
      right={
        <span className="text-[10px] text-[#9CA3AF]">
          potential {fmtUsdShort(r.potential_revenue)} → awarded{" "}
          {fmtUsdShort(r.awarded_revenue)}
        </span>
      }
    >
      <div className="space-y-1.5">
        <Bar
          label="Presented"
          value={r.presented}
          base={r.presented}
          colour="#1B3A5C"
          strong
          title="Every spot opportunity that reached us."
        />
        <Bar
          label="Quoted"
          value={r.quoted}
          base={r.presented}
          colour="#2563EB"
          strong
          title="We put a price on it. Share of Presented."
        />
        <Bar
          label="Skipped"
          value={r.skipped}
          base={r.presented}
          colour="#B45309"
          title="Presented but never priced. Share of Presented. The reason is not recorded in this data source."
        />
        <div className="!mt-3 border-t border-dashed border-[#E5E7EB] pt-2 text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
          Of the {fmtCount(r.quoted)} quoted
        </div>
        {STAGES.map((s) => (
          <Bar
            key={String(s.key)}
            label={s.label}
            value={r[s.key] as number}
            base={r.quoted}
            colour={s.colour}
            title={s.title}
          />
        ))}
      </div>

      <Footnote>
        The stages <strong>partition</strong> the population: Presented = Quoted +
        Skipped, and the seven rows above add back to Quoted
        {reconciles ? "" : " — ⚠ they do not, which means a status escaped its bucket"}.
        Win rate on the cards above is Won ÷ {fmtCount(r.decided)} <em>decided</em>{" "}
        quotes, so the {fmtCount(r.in_play)} still in play neither count as losses nor
        vanish from the base.
      </Footnote>
    </Panel>
  )
}
