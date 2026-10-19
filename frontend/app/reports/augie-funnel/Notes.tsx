"use client"

import { useState } from "react"
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react"
import { fmtNaiveStamp, type AugieFreshness } from "@/lib/augie-funnel-api"

/** `webhooks_received` is a timestamptz (offset-bearing ISO) — render it in
 *  Chicago time. `loads_updated` is a naive CST wall clock — print its parts. */
function fmtTz(v: string | null): string {
  if (!v) return "—"
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return v
  return d.toLocaleString("en-US", {
    timeZone: "America/Chicago",
    month: "2-digit",
    day: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
}

export function FreshnessLine({
  data,
  error,
}: {
  data: AugieFreshness | undefined
  error: unknown
}) {
  if (error) {
    return (
      <p className="text-[11px] text-[#991B1B]">
        Could not read data freshness: {error instanceof Error ? error.message : "unknown error"}
      </p>
    )
  }
  if (!data) return null
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-[#6B7280]">
        Data as of {fmtNaiveStamp(data.loads_updated)} CST (when the McLeod load feed last
        updated) · Augment callbacks as of {fmtTz(data.webhooks_received)} CST
      </p>
      {data.is_stale ? (
        <div className="flex items-start gap-2 rounded-lg border border-[#FECACA] bg-[#FEF2F2] px-3 py-2 text-xs text-[#991B1B]">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            The load feed looks stalled
            {data.loads_stale_minutes !== null
              ? ` — no update for ${Math.round(data.loads_stale_minutes / 60)} h`
              : ""}
            . Recent pickups may be missing, so low counts here are not necessarily low
            activity.
          </span>
        </div>
      ) : null}
    </div>
  )
}

export function HowCounted() {
  const [open, setOpen] = useState(false)
  const Icon = open ? ChevronDown : ChevronRight
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white px-4 py-3 text-xs text-[#4B5563] shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 font-semibold text-[#1B3A5C]"
        aria-expanded={open}
      >
        <Icon className="h-3.5 w-3.5" />
        How this is counted
      </button>
      {open ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 leading-relaxed">
          <li>
            <b>Loads picked up</b> — every load with a pickup scheduled that day (CST), all
            units. A load is counted once per pickup day, so a load with legs on two days counts
            twice and a date range always equals the sum of its days.
          </li>
          <li>
            <b>Sent to Augie</b> — Augment accepted the load, so Augie will follow up with the
            carrier. A status showing in the Augie app is not enough; the grey line under the box
            shows how many loads carry one, so you can see the gap.
          </li>
          <li>
            <b>Carrier contacted</b> — Augie got through to the carrier: a completed call, or the
            carrier answered by phone or e-mail.
          </li>
          <li>
            <b>Carrier gave an update</b> — the carrier came back with a phone update, a
            phone/e-mail tracking event or a stop update (the same rule as the Augie Daily
            Activity e-mail). <b>Sent, no update yet</b> is everything sent without one.
          </li>
          <li>
            <b>% sent</b> and the <b>Not sent to Augie</b> reasons are shares of loads picked up;{" "}
            <b>Contacted %</b> and <b>% with update</b> are shares of loads sent to Augie. A{" "}
            <b>—</b> means there is nothing to divide by (e.g. no loads sent).
          </li>
          <li>
            Each load not sent gets <b>one</b> reason, the first that applies in this order:
            canceled → outside the US → multi-stop or split load → no carrier assigned yet →
            other settings. The reasons therefore add up to Not sent to Augie exactly.
          </li>
        </ul>
      ) : null}
    </div>
  )
}
