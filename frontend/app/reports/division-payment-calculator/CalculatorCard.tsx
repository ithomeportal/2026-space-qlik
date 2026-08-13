"use client"

import { useEffect, useState } from "react"
import { ArrowRight, DollarSign, Loader2, RefreshCw, TrendingDown, TrendingUp, Wallet } from "lucide-react"

import { formatCurrency, useSaveInputs, type Summary } from "@/lib/division-payment-api"
import { DPC, MONO } from "./theme"

interface Props {
  summary: Summary
  /** Dashboard shows read-only values + "Open Calculator"; the Calculator tab
   *  makes them editable. PDF Dashboard Request 2 / Calculator Request 2. */
  editable: boolean
  onOpenCalculator?: () => void
  onViewRecalculations?: () => void
}

/**
 * "A&O — Division Payment Calculator" input card.
 *
 * Monthly Division Profit is **read-only and derived** (Revenue − Carrier Cost).
 * The prototype made it a third free-text field that never recomputed, so the
 * label "Profit = Revenue − Carrier Cost" could sit directly above three numbers
 * that did not satisfy it.
 */
export function CalculatorCard({
  summary, editable, onOpenCalculator, onViewRecalculations,
}: Props) {
  const [revenue, setRevenue] = useState(String(summary.inputs.revenue))
  const [carrierCost, setCarrierCost] = useState(String(summary.inputs.carrier_cost))
  const save = useSaveInputs(summary.year, summary.month)

  // Re-seed the inputs whenever the selected month changes — otherwise the
  // previous month's typed values sit over the new month's data.
  useEffect(() => {
    setRevenue(String(summary.inputs.revenue))
    setCarrierCost(String(summary.inputs.carrier_cost))
  }, [summary.year, summary.month, summary.inputs.revenue, summary.inputs.carrier_cost])

  const revNum = Number(revenue)
  const costNum = Number(carrierCost)
  const valid = Number.isFinite(revNum) && Number.isFinite(costNum) && revNum >= 0 && costNum >= 0
  const profit = valid ? revNum - costNum : summary.inputs.profit
  const dirty =
    valid && (revNum !== summary.inputs.revenue || costNum !== summary.inputs.carrier_cost)

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

      <div className="mt-3 space-y-3">
        <Field
          label="Monthly Revenue"
          icon={<TrendingUp className="h-3.5 w-3.5 text-[#94a3b8]" />}
          value={revenue}
          onChange={setRevenue}
          editable={editable}
          display={formatCurrency(summary.inputs.revenue)}
        />
        <Field
          label="Carrier Cost"
          icon={<TrendingDown className="h-3.5 w-3.5 text-[#94a3b8]" />}
          value={carrierCost}
          onChange={setCarrierCost}
          editable={editable}
          display={formatCurrency(summary.inputs.carrier_cost)}
        />
        <div>
          <label className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[#475569]">
            <Wallet className="h-3.5 w-3.5 text-[#94a3b8]" />
            Monthly Division Profit
          </label>
          <div
            className="mt-1 flex items-center gap-2 rounded-lg border px-3 py-2.5"
            style={{ background: "#f8fafc", borderColor: DPC.border }}
          >
            <DollarSign className="h-4 w-4 text-[#94a3b8]" />
            <span className={`text-lg font-semibold ${MONO}`} style={{ color: DPC.navy }}>
              {formatCurrency(profit)}
            </span>
          </div>
          <p className="mt-1 text-[10px] text-[#94a3b8]">Profit = Revenue − Carrier Cost</p>
        </div>
      </div>

      {editable ? (
        <button
          type="button"
          disabled={!dirty || save.isPending}
          onClick={() =>
            save.mutate({ revenue: revNum, carrier_cost: costNum, profit: revNum - costNum })
          }
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-40"
          style={{ background: DPC.navy }}
        >
          {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {dirty ? "Save Revenue & Carrier Cost" : "Saved"}
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

function Field({
  label, icon, value, onChange, editable, display,
}: {
  label: string
  icon: React.ReactNode
  value: string
  onChange: (v: string) => void
  editable: boolean
  display: string
}) {
  return (
    <div>
      <label className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[#475569]">
        {icon}
        {label}
      </label>
      <div
        className="mt-1 flex items-center gap-2 rounded-lg border px-3 py-2.5"
        style={{ background: editable ? "#ffffff" : "#f8fafc", borderColor: DPC.border }}
      >
        <DollarSign className="h-4 w-4 text-[#94a3b8]" />
        {editable ? (
          <input
            type="number"
            min={0}
            step="0.01"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            aria-label={label}
            className={`w-full bg-transparent text-lg font-semibold outline-none ${MONO}`}
            style={{ color: DPC.navy }}
          />
        ) : (
          <span className={`text-lg font-semibold ${MONO}`} style={{ color: DPC.navy }}>
            {display}
          </span>
        )}
      </div>
    </div>
  )
}
