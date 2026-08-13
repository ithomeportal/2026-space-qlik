"use client"

import { AlertTriangle, CheckCircle2, Target, TrendingDown, Wallet } from "lucide-react"

import { formatCurrency, formatPct, type Summary } from "@/lib/division-payment-api"
import { DPC, MONO } from "./theme"

export type BreakdownSection = "tariff" | "deductions" | "net" | null

interface Props {
  summary: Summary
  /** Which panel is open. Single-open accordion, like the prototype. */
  open: BreakdownSection
  onToggle: (section: Exclude<BreakdownSection, null>) => void
}

/**
 * The four KPIs — PDF Dashboard Request 3.
 *
 * Clickable: Tariff, Deductions, Net Payment (each opens its breakdown below the
 * grid). Profit Margin is not clickable — it has no breakdown in the spec.
 *
 * ⚠ The Tariff card is only clickable when a tariff was actually charged. An
 * affordance that opens an empty panel reads as a broken report.
 */
export function KpiCards({ summary, open, onToggle }: Props) {
  const hasTariff = summary.penalty_fee > 0

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-2">
      {/* Profit Margin — static */}
      <div
        className="rounded-xl border p-4"
        style={
          summary.meets_target
            ? { background: "#ffffff", borderColor: DPC.border }
            : { background: "#fffbeb", borderColor: "#fde68a" }
        }
      >
        <div className="flex items-start justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-[#475569]">
            Profit Margin
          </span>
          <span
            className="grid h-7 w-7 place-items-center rounded-lg"
            style={{ background: summary.meets_target ? "#dcfce7" : "#fef3c7" }}
          >
            {summary.meets_target ? (
              <CheckCircle2 className="h-4 w-4 text-green-600" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-amber-600" />
            )}
          </span>
        </div>
        <div className="mt-5 flex items-baseline gap-2">
          <span
            className={`text-3xl font-bold ${MONO}`}
            style={{ color: summary.meets_target ? DPC.navy : "#b45309" }}
          >
            {formatPct(summary.margin_pct)}
          </span>
          <span className="text-xs text-[#94a3b8]">
            Target: {summary.target_margin_pct}%
          </span>
        </div>
        <p className="mt-4 text-[11px] text-[#94a3b8]">
          {summary.meets_target ? "On target — no tariff" : "Below target — tariff applies"}
        </p>
      </div>

      {/* Tariff */}
      <KpiButton
        label="Tariff"
        hint={hasTariff ? "click for breakdown" : undefined}
        active={open === "tariff"}
        disabled={!hasTariff}
        onClick={() => onToggle("tariff")}
        icon={<Target className={`h-4 w-4 ${hasTariff ? "text-red-500" : "text-slate-400"}`} />}
        iconBg={hasTariff ? "#fee2e2" : "#f1f5f9"}
        style={
          hasTariff
            ? { background: "#fef2f2", borderColor: "#fecaca" }
            : { background: "#ffffff", borderColor: DPC.border }
        }
        value={hasTariff ? `-${formatCurrency(summary.penalty_fee)}` : formatCurrency(0)}
        valueColor={hasTariff ? DPC.danger : "#cbd5e1"}
        footer={hasTariff ? "Charged for missing 10% target" : "No tariff this month"}
      />

      {/* Deductions */}
      <KpiButton
        label="Deductions"
        hint="click for breakdown"
        active={open === "deductions"}
        onClick={() => onToggle("deductions")}
        icon={<TrendingDown className="h-4 w-4 text-red-500" />}
        iconBg="#fee2e2"
        style={{ background: "#ffffff", borderColor: DPC.border }}
        value={`-${formatCurrency(summary.gl_deductions)}`}
        valueColor={DPC.danger}
        footer={`${summary.gl_included_count} of ${summary.gl_row_count} accounts`}
      />

      {/* Net Payment */}
      <KpiButton
        label="Net Payment"
        hint="click for breakdown"
        active={open === "net"}
        onClick={() => onToggle("net")}
        icon={<Wallet className="h-4 w-4" style={{ color: DPC.gold }} />}
        iconBg="#ffffff1a"
        style={{ background: DPC.navy, borderColor: DPC.navy }}
        value={formatCurrency(summary.net_payment_adjusted)}
        valueColor="#ffffff"
        labelColor="#ffffff"
        footer="To division · click for breakdown"
        footerColor="#94a3b8"
        rule={DPC.gold}
      />
    </div>
  )
}

interface KpiButtonProps {
  label: string
  hint?: string
  value: string
  valueColor: string
  footer: string
  footerColor?: string
  labelColor?: string
  icon: React.ReactNode
  iconBg: string
  style: React.CSSProperties
  active: boolean
  disabled?: boolean
  onClick: () => void
  rule?: string
}

function KpiButton({
  label, hint, value, valueColor, footer, footerColor, labelColor,
  icon, iconBg, style, active, disabled, onClick, rule,
}: KpiButtonProps) {
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      aria-expanded={disabled ? undefined : active}
      className={`relative overflow-hidden rounded-xl border p-4 text-left transition ${
        disabled ? "cursor-default" : "hover:shadow-md"
      } ${active ? "ring-2 ring-offset-1" : ""}`}
      style={{ ...style, ...(active ? { boxShadow: `0 0 0 2px ${DPC.gold}` } : {}) }}
    >
      <div className="flex items-start justify-between">
        <span
          className="text-[11px] font-semibold uppercase tracking-wide"
          style={{ color: labelColor ?? "#475569" }}
        >
          {label}
          {hint && !disabled ? (
            <span className="ml-1.5 font-normal normal-case tracking-normal text-[#94a3b8]">
              · {hint}
            </span>
          ) : null}
        </span>
        <span className="grid h-7 w-7 place-items-center rounded-lg" style={{ background: iconBg }}>
          {icon}
        </span>
      </div>
      <div className={`mt-5 text-3xl font-bold ${MONO}`} style={{ color: valueColor }}>
        {value}
      </div>
      <p className="mt-4 text-[11px]" style={{ color: footerColor ?? "#94a3b8" }}>
        {footer}
      </p>
      {rule ? (
        <span className="absolute inset-x-0 bottom-0 h-1" style={{ background: rule }} />
      ) : null}
    </button>
  )
}
