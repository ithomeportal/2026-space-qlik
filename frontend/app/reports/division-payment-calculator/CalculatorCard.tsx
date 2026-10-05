"use client"

import { useEffect, useRef, useState } from "react"
import {
  AlertTriangle,
  ArrowRight,
  Database,
  DollarSign,
  Loader2,
  PencilLine,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react"

import {
  formatCurrency,
  useSaveOverrides,
  type OverrideBody,
  type Summary,
} from "@/lib/division-payment-api"
import { DPC, MONO } from "./theme"

interface Props {
  summary: Summary
  /** Dashboard shows read-only values + "Open Calculator"; the Calculator tab
   *  makes them editable. PDF Dashboard Request 2 / Calculator Request 2. */
  editable: boolean
  onOpenCalculator?: () => void
  onViewRecalculations?: () => void
}

type FieldKey = keyof OverrideBody

interface FieldSpec {
  key: FieldKey
  label: string
  icon: typeof TrendingUp
  /** Profit can legitimately be negative (a losing month); revenue and carrier
   *  cost cannot. */
  allowNegative: boolean
  caption?: string
}

const FIELDS: FieldSpec[] = [
  { key: "revenue", label: "Monthly Revenue", icon: TrendingUp, allowNegative: false },
  { key: "carrier_cost", label: "Carrier Cost", icon: TrendingDown, allowNegative: false },
  {
    key: "profit",
    label: "Monthly Division Profit",
    icon: Wallet,
    allowNegative: true,
    caption: "Profit = SUM(margin_amt) · v4 TEAM-DFW",
  },
]

type Drafts = Record<FieldKey, string>

const cents = (n: number) => Math.round(n * 100)

function seedDrafts(summary: Summary): Drafts {
  return {
    revenue: String(summary.inputs.revenue),
    carrier_cost: String(summary.inputs.carrier_cost),
    profit: String(summary.inputs.profit),
  }
}

function parseDraft(draft: string, allowNegative: boolean): number | null {
  if (draft.trim() === "") return null
  const n = Number(draft)
  if (!Number.isFinite(n)) return null
  if (!allowNegative && n < 0) return null
  return Math.round(n * 100) / 100
}


/**
 * "A&O — Division Payment Calculator" input card.
 *
 * Bruno PDF 2026-10-05: the three figures now come from the datalake (v4,
 * TEAM-DFW, by origin_actual_departure) and each may be manually overridden.
 * Profit is NO LONGER Revenue − Carrier Cost computed here — it is
 * SUM(margin_amt) from the backend (or its override). `summary.inputs.*` is the
 * effective value; this card never derives a money figure, it only decides
 * which override to send.
 *
 * Save rule, per field: an untouched field is NOT sent (the server keeps it —
 * resending it from this tab's cache could overwrite another user's save); a
 * touched field whose value equals the datalake to the cent sends `null` —
 * typing the datalake number back IS clearing the override, so the month stops
 * being flagged as overridden.
 */
export function CalculatorCard({
  summary, editable, onOpenCalculator, onViewRecalculations,
}: Props) {
  const [drafts, setDrafts] = useState<Drafts>(() => seedDrafts(summary))
  const save = useSaveOverrides(summary.year, summary.month)
  const dlAvailable = summary.datalake.available

  // Re-seed on a month switch (else the previous month's typed values sit over
  // the new month's data). On a server-value change within the SAME month —
  // a background refetch, a GL edit's invalidation — re-seed only the fields
  // the user has not edited, so a value being typed is never wiped.
  const { revenue, carrier_cost, profit } = summary.inputs
  const seeded = useRef({ key: "", values: seedDrafts(summary) })
  useEffect(() => {
    const key = `${summary.year}-${summary.month}`
    const next: Drafts = {
      revenue: String(revenue),
      carrier_cost: String(carrier_cost),
      profit: String(profit),
    }
    const prev = seeded.current
    seeded.current = { key, values: next }
    if (prev.key !== key) {
      setDrafts(next)
      return
    }
    setDrafts((d) => ({
      revenue: d.revenue === prev.values.revenue ? next.revenue : d.revenue,
      carrier_cost: d.carrier_cost === prev.values.carrier_cost ? next.carrier_cost : d.carrier_cost,
      profit: d.profit === prev.values.profit ? next.profit : d.profit,
    }))
  }, [summary.year, summary.month, revenue, carrier_cost, profit])

  const parsed = FIELDS.map((f) => ({ f, value: parseDraft(drafts[f.key], f.allowNegative) }))
  const valid = parsed.every((p) => p.value !== null)
  const touched = parsed.filter(
    (p) => p.value !== null && cents(p.value) !== cents(summary.inputs[p.f.key]),
  )
  const dirty = valid && touched.length > 0

  const buildBody = (): OverrideBody =>
    parsed.reduce<OverrideBody>((body, { f, value }) => {
      if (value === null || cents(value) === cents(summary.inputs[f.key])) return body
      // With the datalake unreachable its figures are not a trustworthy
      // baseline, so a typed value is always kept as an override.
      const matchesDatalake = dlAvailable && cents(value) === cents(summary.datalake[f.key])
      return { ...body, [f.key]: matchesDatalake ? null : value }
    }, {})

  const resetField = (key: FieldKey) => save.mutate({ [key]: null })

  return (
    <div className="rounded-xl border bg-white p-4" style={{ borderColor: DPC.border }}>
      <div className="flex items-center gap-2.5 border-b pb-3" style={{ borderColor: DPC.border }}>
        <span
          className="grid h-9 w-9 place-items-center rounded-lg text-[11px] font-bold"
          style={{ background: DPC.navy, color: DPC.gold }}
        >
          A&amp;O
        </span>
        <div>
          <p className="text-base font-bold" style={{ color: DPC.navy }}>
            A&amp;O
          </p>
          <p className="text-[11px] text-[#94a3b8]">Division Payment Calculator</p>
        </div>
      </div>

      {summary.overridden ? (
        <div
          className="mt-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold"
          style={{
            background: DPC.overrideBg,
            borderColor: `${DPC.overrideText}55`,
            color: DPC.overrideText,
          }}
          title={overrideTitle(summary)}
        >
          <PencilLine className="h-4 w-4 shrink-0" />
          This month has manual overrides
        </div>
      ) : null}

      {!dlAvailable ? (
        <p className="mt-2 flex items-center gap-1.5 text-[11px] text-[#b45309]">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          Datalake unavailable — showing saved values
        </p>
      ) : null}

      <div className="mt-3 space-y-3">
        {FIELDS.map((f) => (
          <Field
            key={f.key}
            spec={f}
            value={drafts[f.key]}
            onChange={(v) => setDrafts((prev) => ({ ...prev, [f.key]: v }))}
            editable={editable}
            display={formatCurrency(summary.inputs[f.key])}
            override={summary.overrides[f.key]}
            datalakeValue={summary.datalake[f.key]}
            onReset={editable && dlAvailable ? () => resetField(f.key) : undefined}
            resetting={save.isPending}
          />
        ))}
      </div>

      {editable ? (
        <button
          type="button"
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate(buildBody())}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-40"
          style={{ background: DPC.navy }}
        >
          {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {dirty ? "Save" : valid ? "Saved" : "Enter valid amounts"}
        </button>
      ) : null}

      {onOpenCalculator ? (
        <button
          type="button"
          onClick={onOpenCalculator}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border px-3 py-2.5 text-sm font-medium transition hover:bg-[#f8fafc]"
          style={{ borderColor: DPC.border, color: DPC.navy }}
        >
          Open Calculator <ArrowRight className="h-4 w-4" />
        </button>
      ) : null}

      {onViewRecalculations && summary.recalcs.length > 0 ? (
        <button
          type="button"
          onClick={onViewRecalculations}
          className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg border px-3 py-2.5 text-sm font-medium transition hover:bg-[#fffbeb]"
          style={{ borderColor: `${DPC.gold}66`, color: DPC.gold }}
        >
          <RefreshCw className="h-4 w-4" />
          View Recalculations ({summary.recalcs.length}) <ArrowRight className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  )
}

function overrideTitle(summary: Summary): string | undefined {
  const { updated_at, updated_by } = summary.overrides
  if (!updated_at && !updated_by) return undefined
  return `Last changed${updated_by ? ` by ${updated_by}` : ""}${updated_at ? ` · ${updated_at}` : ""}`
}

function Field({
  spec, value, onChange, editable, display, override, datalakeValue, onReset, resetting,
}: {
  spec: FieldSpec
  value: string
  onChange: (v: string) => void
  editable: boolean
  display: string
  override: number | null
  datalakeValue: number
  onReset?: () => void
  resetting: boolean
}) {
  const Icon = spec.icon
  const isOverride = override !== null
  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5">
        <label className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[#475569]">
          <Icon className="h-3.5 w-3.5 text-[#94a3b8]" />
          {spec.label}
        </label>
        <SourceBadge override={isOverride} />
      </div>
      <div
        className="mt-1 flex items-center gap-2 rounded-lg border px-3 py-2.5"
        style={{
          background: editable ? "#ffffff" : "#f8fafc",
          borderColor: isOverride ? `${DPC.overrideText}66` : DPC.border,
        }}
      >
        <DollarSign className="h-4 w-4 text-[#94a3b8]" />
        {editable ? (
          <input
            type="number"
            min={spec.allowNegative ? undefined : 0}
            step="0.01"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            aria-label={spec.label}
            className={`w-full bg-transparent text-lg font-semibold outline-none ${MONO}`}
            style={{ color: DPC.navy }}
          />
        ) : (
          <span className={`text-lg font-semibold ${MONO}`} style={{ color: DPC.navy }}>
            {display}
          </span>
        )}
      </div>
      {isOverride ? (
        <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-[#64748b]">
          <span>
            Datalake: <span className={MONO}>{formatCurrency(datalakeValue)}</span>
          </span>
          {onReset ? (
            <button
              type="button"
              onClick={onReset}
              disabled={resetting}
              className="font-semibold underline-offset-2 hover:underline disabled:opacity-40"
              style={{ color: DPC.overrideText }}
            >
              Reset to datalake
            </button>
          ) : null}
        </div>
      ) : null}
      {spec.caption ? <p className="mt-1 text-[10px] text-[#94a3b8]">{spec.caption}</p> : null}
    </div>
  )
}

function SourceBadge({ override }: { override: boolean }) {
  if (override) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-semibold"
        style={{ background: DPC.overrideBg, color: DPC.overrideText }}
      >
        <PencilLine className="h-3 w-3" />
        Manual override
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded bg-[#f1f5f9] px-1.5 py-0.5 text-[9px] font-medium text-[#64748b]">
      <Database className="h-3 w-3" />
      Datalake
    </span>
  )
}
