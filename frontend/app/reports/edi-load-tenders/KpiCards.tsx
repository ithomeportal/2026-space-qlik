"use client"

import type { EdiSummary } from "@/lib/edi-load-tenders-api"

const nf = new Intl.NumberFormat("en-US")

function pct(v: number | null | undefined) {
  return v === null || v === undefined ? "—" : `${v.toFixed(1)}%`
}

interface CardProps {
  label: string
  value: string
  hint?: string
  tone?: "default" | "warn" | "bad"
}

function Card({ label, value, hint, tone = "default" }: CardProps) {
  const ring =
    tone === "bad"
      ? "border-red-200 bg-red-50"
      : tone === "warn"
        ? "border-amber-200 bg-amber-50"
        : "border-slate-200 bg-white"
  const num =
    tone === "bad" ? "text-red-700" : tone === "warn" ? "text-amber-700" : "text-slate-900"
  return (
    <div className={`rounded-lg border p-4 ${ring}`}>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${num}`}>{value}</div>
      {hint ? <div className="mt-1 text-xs text-slate-500">{hint}</div> : null}
    </div>
  )
}

export function KpiCards({ data }: { data?: EdiSummary }) {
  if (!data) {
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-lg border border-slate-200 bg-slate-50" />
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Card
        label="Shipments tendered"
        value={nf.format(data.shipments)}
        hint={`${nf.format(data.tender_messages)} EDI messages`}
      />
      <Card
        label="Order created"
        value={nf.format(data.created)}
        hint={`${pct(data.create_rate)} of shipments`}
      />
      <Card
        label="Never created"
        value={data.team_filtered ? "n/a" : nf.format(data.never_created)}
        hint={
          data.team_filtered
            ? "no team on an uncreated tender"
            : "tendered, no order raised"
        }
        tone={data.team_filtered ? "default" : "warn"}
      />
      <Card
        label="Cancelled by customer"
        value={nf.format(data.cust_cancelled)}
        hint={`${pct(data.cancel_rate)} of shipments`}
      />
      <Card
        label="Cancelled by us"
        value={nf.format(data.we_cancelled)}
        hint={`${pct(data.actioned_rate)} of the ${nf.format(
          data.cust_cancelled_created,
        )} we could action`}
      />
      <Card
        label="Cancel not actioned"
        value={nf.format(data.cancel_not_actioned)}
        hint="customer cancelled, order still open here"
        tone={data.cancel_not_actioned > 0 ? "bad" : "default"}
      />
    </div>
  )
}
