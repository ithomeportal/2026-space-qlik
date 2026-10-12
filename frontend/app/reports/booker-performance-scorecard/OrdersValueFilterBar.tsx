"use client"

import { useEffect, useState } from "react"
import { Filter, X } from "lucide-react"
import type {
  OrdersValueColumn,
  OrdersValueFilters,
  OrdersValueOp,
} from "@/lib/booker-scorecard-api"

/** Bruno's own example values (PDF 2026-10-12) double as the placeholders. */
const COLUMNS: ReadonlyArray<{ key: OrdersValueColumn; label: string; example: string }> = [
  { key: "revenue", label: "Revenue", example: "200" },
  { key: "cost", label: "Carrier Cost", example: "150" },
  { key: "profit", label: "Profit", example: "50" },
]

const OPS: ReadonlyArray<{ key: OrdersValueOp; label: string }> = [
  { key: "eq", label: "=" },
  { key: "gte", label: "≥" },
  { key: "lte", label: "≤" },
]

const DEBOUNCE_MS = 400

interface Draft {
  op: OrdersValueOp
  text: string
}

type Drafts = Record<OrdersValueColumn, Draft>

const EMPTY: Drafts = {
  revenue: { op: "eq", text: "" },
  cost: { op: "eq", text: "" },
  profit: { op: "eq", text: "" },
}

/** "$1,200.50" → 1200.5; blank → null; anything unparseable → NaN. */
function parseAmount(text: string): number | null {
  const t = text.replace(/[$,\s]/g, "")
  if (t === "") return null
  const n = Number(t)
  return Number.isFinite(n) ? n : Number.NaN
}

function toFilters(drafts: Drafts): OrdersValueFilters {
  const out: OrdersValueFilters = {}
  for (const { key } of COLUMNS) {
    const v = parseAmount(drafts[key].text)
    if (v !== null && Number.isFinite(v)) out[key] = { op: drafts[key].op, value: v }
  }
  return out
}

interface Props {
  onChange: (filters: OrdersValueFilters) => void
}

/**
 * Per-column amount filters for the Scenario tab's Orders table (Bruno PDF
 * 2026-10-12: "Revenue = '200', Carrier Cost = '150', Profit = '50'"). Typing
 * is debounced; an unparseable amount is outlined red and ignored rather than
 * silently filtering on something else. They filter the scenario-ADJUSTED
 * amounts — the numbers the table shows.
 */
export function OrdersValueFilterBar({ onChange }: Props) {
  const [drafts, setDrafts] = useState<Drafts>(EMPTY)

  useEffect(() => {
    const id = setTimeout(() => onChange(toFilters(drafts)), DEBOUNCE_MS)
    return () => clearTimeout(id)
  }, [drafts, onChange])

  const set = (key: OrdersValueColumn, patch: Partial<Draft>) =>
    setDrafts((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }))
  const active = COLUMNS.some(({ key }) => drafts[key].text.trim() !== "")

  return (
    <div className="mb-3 rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
          <Filter className="h-3 w-3" />
          Filter orders
        </span>
        {COLUMNS.map(({ key, label, example }) => {
          const d = drafts[key]
          const invalid = Number.isNaN(parseAmount(d.text) as number)
          return (
            <label key={key} className="flex items-center gap-1 text-xs text-[#374151]">
              <span className="font-medium">{label}</span>
              <select
                aria-label={`${label} operator`}
                value={d.op}
                onChange={(e) => set(key, { op: e.target.value as OrdersValueOp })}
                className="rounded border border-[#D1D5DB] bg-white px-1 py-0.5 text-xs"
              >
                {OPS.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </select>
              <input
                type="text"
                inputMode="decimal"
                aria-label={`${label} amount`}
                aria-invalid={invalid}
                placeholder={example}
                value={d.text}
                onChange={(e) => set(key, { text: e.target.value })}
                className={`w-20 rounded border bg-white px-1.5 py-0.5 text-right text-xs tabular-nums ${
                  invalid ? "border-[#DC2626] outline-[#DC2626]" : "border-[#D1D5DB]"
                }`}
              />
            </label>
          )
        })}
        {active && (
          <button
            type="button"
            onClick={() => setDrafts(EMPTY)}
            className="flex items-center gap-1 rounded border border-[#E5E7EB] bg-white px-2 py-0.5 text-[11px] text-[#374151] hover:bg-[#F3F4F6]"
          >
            <X className="h-3 w-3" />
            Clear
          </button>
        )}
      </div>
      {active && (
        <p className="mt-1.5 text-[10px] text-[#6B7280]">
          Filters apply to the scenario-adjusted amounts and narrow this table and its
          Totals row only — the KPI cards above still cover every order. &quot;=&quot;
          matches to the cent.
        </p>
      )}
    </div>
  )
}
