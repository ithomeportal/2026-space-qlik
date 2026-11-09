"use client"

import { Fragment, useState } from "react"
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, MinusCircle } from "lucide-react"
import {
  AUGIE_MISSING_FIELDS,
  DASH,
  MISSING_FIELD_LABELS,
  REASON_LABELS,
  fmtInt,
  fmtNaiveStamp,
  type AugieFieldStatus,
  type AugieMissingField,
  type AugieMissingResult,
  type AugieMissingRow,
} from "@/lib/augie-funnel-api"
import { EmptyBlock, ErrorBlock, LoadingBlock, Panel } from "./Ui"

interface Props {
  data: AugieMissingResult | undefined
  loading: boolean
  error: unknown
  field: AugieMissingField | "all"
  onField: (f: AugieMissingField | "all") => void
}

const STATUS_UI: Record<AugieFieldStatus, { text: string; cls: string; Icon: typeof AlertCircle }> = {
  missing: { text: "Missing", cls: "text-[#B91C1C]", Icon: AlertCircle },
  available: { text: "Available", cls: "text-[#15803D]", Icon: CheckCircle2 },
  "n/a": { text: "n/a — not sent to Augie", cls: "text-[#9CA3AF]", Icon: MinusCircle },
}

function missingOf(r: AugieMissingRow): AugieMissingField[] {
  return AUGIE_MISSING_FIELDS.filter((k) => r.fields[k] === "missing")
}

function Chip({
  active,
  label,
  count,
  onClick,
}: {
  active: boolean
  label: string
  count?: number
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${
        active
          ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
          : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
      }`}
    >
      {label}
      {count !== undefined ? <span className="ml-1 tabular-nums opacity-80">{fmtInt(count)}</span> : null}
    </button>
  )
}

function Details({ r }: { r: AugieMissingRow }) {
  return (
    <div className="grid gap-x-8 gap-y-1 px-10 py-2 sm:grid-cols-2">
      {AUGIE_MISSING_FIELDS.map((k) => {
        const s = STATUS_UI[r.fields[k]]
        return (
          <div key={k} className="flex items-center justify-between gap-3 text-xs">
            <span className="flex items-center gap-2 text-[#374151]">
              <s.Icon className={`h-3.5 w-3.5 ${s.cls}`} />
              {MISSING_FIELD_LABELS[k]}
            </span>
            <span className={s.cls}>{s.text}</span>
          </div>
        )
      })}
    </div>
  )
}

function Row({ r }: { r: AugieMissingRow }) {
  const [open, setOpen] = useState(false)
  const missing = missingOf(r)
  const team = [r.unit, r.team].filter(Boolean).join(" / ") || DASH
  return (
    <Fragment>
      <tr className="cursor-pointer hover:bg-[#F9FAFB]" onClick={() => setOpen((o) => !o)}>
        <td className="w-8 px-2 py-1.5 text-[#6B7280]">
          <button
            type="button"
            aria-label={open ? "Hide details" : "Show details"}
            aria-expanded={open}
            onClick={(e) => {
              e.stopPropagation()
              setOpen((o) => !o)
            }}
          >
            {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        </td>
        <td className="whitespace-nowrap px-3 py-1.5">
          <div className="font-mono text-[#1D4ED8]">{r.order_id}</div>
          <div className="text-[11px] text-[#6B7280]">{team}</div>
        </td>
        <td className="whitespace-nowrap px-3 py-1.5 tabular-nums">{fmtNaiveStamp(r.pickup_day)}</td>
        <td className="max-w-[220px] truncate px-3 py-1.5" title={r.customer ?? ""}>
          {r.customer || DASH}
        </td>
        <td className="max-w-[220px] truncate px-3 py-1.5" title={r.carrier ?? ""}>
          {r.carrier || DASH}
        </td>
        <td className="px-3 py-1.5">
          <div className="flex flex-wrap gap-1">
            {missing.map((k) => (
              <span
                key={k}
                className="rounded border border-[#FECACA] bg-[#FEF2F2] px-1.5 py-0.5 text-[11px] text-[#B91C1C]"
              >
                {MISSING_FIELD_LABELS[k]}
              </span>
            ))}
          </div>
        </td>
        <td className="whitespace-nowrap px-3 py-1.5 text-[11px] text-[#6B7280]">
          {r.tracked ? "Sent to Augie" : `Not sent: ${r.reason ? REASON_LABELS[r.reason] : "Unknown"}`}
        </td>
      </tr>
      {open ? (
        <tr className="bg-[#F9FAFB]">
          <td colSpan={7}>
            <div className="px-2 pt-2 text-[11px] font-semibold text-[#374151]">
              Missing information details
            </div>
            <Details r={r} />
          </td>
        </tr>
      ) : null}
    </Fragment>
  )
}

export function MissingInfoTable({ data, loading, error, field, onField }: Props) {
  const rows = data?.rows ?? []
  const subtitle = data
    ? `${fmtInt(data.withMissing)} of ${fmtInt(data.checked)} loads miss one or more fields` +
      (field !== "all" ? ` · ${fmtInt(data.total)} miss ${MISSING_FIELD_LABELS[field]}` : "") +
      (data.truncated ? ` · showing first ${fmtInt(rows.length)}` : "")
    : undefined

  let body
  if (error) body = <ErrorBlock what="the missing information" error={error} />
  else if (loading && rows.length === 0) body = <LoadingBlock />
  else if (rows.length === 0)
    body = <EmptyBlock msg="No load in this window is missing that information." />
  else
    body = (
      <div className="max-h-[640px] overflow-auto">
        <table className="w-full min-w-[960px] text-xs">
          <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-left text-[#6B7280]">
            <tr>
              <th className="w-8" />
              <th className="px-3 py-1.5 font-semibold">Load / Team</th>
              <th className="px-3 py-1.5 font-semibold">Pickup</th>
              <th className="px-3 py-1.5 font-semibold">Customer</th>
              <th className="px-3 py-1.5 font-semibold">Carrier</th>
              <th className="px-3 py-1.5 font-semibold">Missing information</th>
              <th className="px-3 py-1.5 font-semibold">Augie</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {rows.map((r) => (
              <Row key={`${r.order_id}|${r.pickup_day}`} r={r} />
            ))}
          </tbody>
        </table>
      </div>
    )

  return (
    <Panel title="Loads — Missing information" subtitle={subtitle}>
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[11px] text-[#6B7280]">Missing field</span>
        <Chip active={field === "all"} label="All fields" count={data?.withMissing} onClick={() => onField("all")} />
        {AUGIE_MISSING_FIELDS.map((k) => (
          <Chip
            key={k}
            active={field === k}
            label={MISSING_FIELD_LABELS[k]}
            count={data?.counts[k]}
            onClick={() => onField(k)}
          />
        ))}
      </div>
      {body}
      <p className="mt-2 text-[11px] text-[#6B7280]">
        The carrier and driver fields are the ones the Augie app flags under &ldquo;Logs Info&rdquo;, read
        from McLeod. Trailer comes only from Augie&rsquo;s calls, so it is checked only on loads sent to
        Augie. Canceled loads are left out. Missing fields are separate from the reason a load was not
        sent to Augie. Unit, team and the search box above filter this table too.
      </p>
    </Panel>
  )
}
