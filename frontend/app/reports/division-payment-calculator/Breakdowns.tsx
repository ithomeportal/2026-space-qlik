"use client"

import { Info, Target, Wallet, X } from "lucide-react"

import { formatCurrency, type Summary } from "@/lib/division-payment-api"
import { DPC, MONO } from "./theme"

/**
 * The three breakdown panels — PDF Dashboard Requests 4, 5 and 6.
 *
 * Rendered inline below the KPI grid rather than in a modal: the PDF says
 * "display a table at the bottom of the page", and shadcn's Dialog sits on
 * `@base-ui/react`, which this project bans in interactive components on
 * React 18.
 *
 * ⚠ Every figure comes off the `summary` payload. None is recomputed here —
 * that is the whole point of §16, and of this report in particular.
 */

function Panel({
  title, subtitle, icon, onClose, children,
}: {
  title: string
  subtitle: string
  icon: React.ReactNode
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <section className="overflow-hidden rounded-xl border" style={{ borderColor: DPC.border }}>
      <header
        className="flex items-center justify-between px-4 py-3 text-white"
        style={{ background: DPC.navy }}
      >
        <div className="flex items-center gap-2.5">
          <span
            className="grid h-8 w-8 place-items-center rounded-lg"
            style={{ background: "#ffffff1a" }}
          >
            {icon}
          </span>
          <div>
            <h3 className="text-sm font-semibold" style={{ color: DPC.gold }}>
              {title}
            </h3>
            <p className="text-[11px] text-white/60">{subtitle}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close breakdown"
          className="rounded p-1 text-white/60 hover:bg-white/10 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      <div className="bg-white p-4">{children}</div>
    </section>
  )
}

function MiniStat({
  label, value, note, highlight,
}: {
  label: string
  value: string
  note: string
  highlight?: boolean
}) {
  return (
    <div
      className="rounded-lg border p-3"
      style={
        highlight
          ? { background: DPC.tariffPanel, borderColor: "#fcd34d" }
          : { background: "#ffffff", borderColor: DPC.border }
      }
    >
      <p className="text-[10px] font-semibold uppercase tracking-wide text-[#64748b]">{label}</p>
      <p
        className={`mt-1.5 text-lg font-bold ${MONO}`}
        style={{ color: highlight ? "#b45309" : DPC.navy }}
      >
        {value}
      </p>
      <p className="mt-1 text-[10px] text-[#94a3b8]">{note}</p>
    </div>
  )
}

// --- Request 4 -------------------------------------------------------------
export function TariffBreakdown({ summary, onClose }: { summary: Summary; onClose: () => void }) {
  return (
    <Panel
      title="Tariff Breakdown"
      subtitle={`${summary.month_label} — Margin below ${summary.target_margin_pct}% target`}
      icon={<Target className="h-4 w-4" style={{ color: DPC.gold }} />}
      onClose={onClose}
    >
      <div
        className="flex gap-2.5 rounded-lg border p-3 text-xs leading-relaxed"
        style={{ background: DPC.tariffPanel, borderColor: "#fde68a", color: "#78350f" }}
      >
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        <p>
          The <strong>tariff</strong> is a charge applied when the profit margin falls below
          the {summary.target_margin_pct}% target. It equals the difference between what
          Corporate <em>should</em> receive (25% of the target profit) and what Corporate{" "}
          <em>actually</em> receives (25% of the real profit).
        </p>
      </div>

      <div className="mt-3 grid gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
        <MiniStat
          label={`${summary.target_margin_pct}% of Revenue`}
          value={formatCurrency(summary.ten_pct_of_revenue)}
          note="Target profit"
        />
        <MiniStat
          label="25% of Target Profit"
          value={formatCurrency(summary.target_fee)}
          note="Target fee"
        />
        <MiniStat
          label="25% of Actual Profit"
          value={formatCurrency(summary.actual_fee)}
          note="Actual fee"
        />
        <MiniStat
          label="Difference"
          value={formatCurrency(summary.difference)}
          note="Target fee − Actual fee"
        />
        <MiniStat
          label="Tariff"
          value={formatCurrency(summary.penalty_fee)}
          note="Charged to division"
          highlight
        />
      </div>

      <div
        className={`mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg px-4 py-3 text-sm ${MONO}`}
        style={{ background: "#f1f5f9" }}
      >
        <span>
          <strong>{formatCurrency(summary.target_fee)}</strong>{" "}
          <span className="text-[#94a3b8]">(target fee)</span> −{" "}
          <strong>{formatCurrency(summary.actual_fee)}</strong>{" "}
          <span className="text-[#94a3b8]">(actual fee)</span> =
        </span>
        <span className="text-lg font-bold" style={{ color: DPC.danger }}>
          {formatCurrency(summary.difference)}
        </span>
      </div>

      <div
        className="mt-3 flex items-center justify-between rounded-lg px-4 py-3 text-white"
        style={{
          background: `linear-gradient(135deg, ${DPC.container}, ${DPC.navyDeep})`,
          borderBottom: `3px solid ${DPC.danger}`,
        }}
      >
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-white/60">
            Tariff Charged
          </p>
          <p className={`text-2xl font-bold ${MONO}`} style={{ color: DPC.deduction }}>
            -{formatCurrency(summary.penalty_fee)}
          </p>
        </div>
        <Target className="h-8 w-8 opacity-40" />
      </div>
    </Panel>
  )
}

// --- Request 5 -------------------------------------------------------------
export function DeductionsBreakdown({
  summary, onClose,
}: {
  summary: Summary
  onClose: () => void
}) {
  return (
    <Panel
      title="Deductions Breakdown"
      subtitle={`${summary.month_label} · ${summary.gl_included_count} of ${summary.gl_row_count} accounts included`}
      icon={<Wallet className="h-4 w-4" style={{ color: DPC.gold }} />}
      onClose={onClose}
    >
      <div className="flex flex-wrap gap-2.5">
        {summary.gl_categories.map((c) => (
          <div
            key={c.category}
            className="min-w-[150px] flex-1 rounded-lg border p-3"
            style={{ borderColor: DPC.border }}
          >
            <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-[#475569]">
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: c.color }}
                aria-hidden
              />
              {c.label}
            </p>
            <p className={`mt-1.5 text-lg font-bold ${MONO}`} style={{ color: DPC.navy }}>
              {formatCurrency(c.amount)}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[640px] text-xs">
          <thead>
            <tr className="border-b text-[10px] uppercase tracking-wide text-[#64748b]"
                style={{ borderColor: DPC.border }}>
              <th className="px-3 py-2 text-left font-semibold">GL Code</th>
              <th className="px-3 py-2 text-left font-semibold">Category</th>
              <th className="px-3 py-2 text-left font-semibold">Description</th>
              <th className="px-3 py-2 text-right font-semibold">Amount</th>
            </tr>
          </thead>
          <tbody>
            {summary.gl_accounts.filter((a) => a.included).map((a) => {
              const color =
                summary.gl_categories.find((c) => c.category === a.category)?.color ?? "#64748b"
              return (
                <tr key={a.id} className="border-b last:border-0" style={{ borderColor: "#f1f5f9" }}>
                  <td className={`px-3 py-2 text-[#475569] ${MONO}`}>{a.code}</td>
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-1.5">
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ background: color }}
                        aria-hidden
                      />
                      {a.category_label}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-[#334155]">{a.description}</td>
                  <td className={`px-3 py-2 text-right ${MONO}`} style={{ color: DPC.danger }}>
                    -{formatCurrency(a.amount)}
                  </td>
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            {/* colSpan is derived from the header, not typed — a hardcoded one
                shifts money into the wrong column when a column is added (§61). */}
            <tr className="text-white" style={{ background: DPC.navy }}>
              <td className="px-3 py-2.5 font-semibold" colSpan={3}>
                Total Deductions
              </td>
              <td className={`px-3 py-2.5 text-right font-bold ${MONO}`} style={{ color: DPC.deduction }}>
                -{formatCurrency(summary.gl_deductions)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </Panel>
  )
}

// --- Request 6 -------------------------------------------------------------
export function NetPaymentBreakdown({
  summary, onClose,
}: {
  summary: Summary
  onClose: () => void
}) {
  const steps = [
    { n: 1, label: "Monthly Division Profit", value: summary.profit, color: DPC.navy, sign: "" },
    { n: 2, label: "GL Account Deductions", value: summary.gl_deductions, color: DPC.danger, sign: "-" },
    {
      n: 3,
      label: "Corporate Gain (25% + tariff)",
      value: summary.corporate_gain_total,
      color: DPC.gold,
      sign: "-",
    },
  ]

  return (
    <Panel
      title="Net Payment Breakdown"
      subtitle={`${summary.month_label} · How the net payment to A&O is calculated`}
      icon={<Wallet className="h-4 w-4" style={{ color: DPC.gold }} />}
      onClose={onClose}
    >
      <div className="space-y-2">
        {steps.map((s) => (
          <div
            key={s.n}
            className="flex items-center justify-between rounded-lg border px-3 py-2.5"
            style={{ borderColor: DPC.border, background: "#f8fafc" }}
          >
            <span className="flex items-center gap-2.5 text-sm">
              <span
                className="grid h-6 w-6 place-items-center rounded-full text-[11px] font-bold text-white"
                style={{ background: s.n === 1 ? DPC.navy : `${s.color}cc` }}
              >
                {s.n}
              </span>
              {s.label}
            </span>
            <span className={`font-semibold ${MONO}`} style={{ color: s.color }}>
              {s.sign}
              {formatCurrency(s.value)}
            </span>
          </div>
        ))}

        {summary.recalc_ao_adjustment !== 0 ? (
          <div
            className="flex items-center justify-between rounded-lg border px-3 py-2.5"
            style={{ borderColor: "#fde68a", background: DPC.tariffPanel }}
          >
            <span className="flex items-center gap-2.5 text-sm">
              <span
                className="grid h-6 w-6 place-items-center rounded-full text-[11px] font-bold text-white"
                style={{ background: "#b45309" }}
              >
                4
              </span>
              Recalculation adjustment (75% of profit delta)
            </span>
            <span
              className={`font-semibold ${MONO}`}
              style={{ color: summary.recalc_ao_adjustment >= 0 ? DPC.positive : DPC.danger }}
            >
              {summary.recalc_ao_adjustment >= 0 ? "+" : "-"}
              {formatCurrency(Math.abs(summary.recalc_ao_adjustment))}
            </span>
          </div>
        ) : null}
      </div>

      <div className="mt-3 rounded-lg px-4 py-3" style={{ background: "#f1f5f9" }}>
        <p className="text-[10px] font-semibold uppercase tracking-wide text-[#64748b]">Formula</p>
        <p className={`mt-1 text-sm ${MONO}`}>
          {formatCurrency(summary.profit)} − {formatCurrency(summary.gl_deductions)} −{" "}
          {formatCurrency(summary.corporate_gain_total)}
          {summary.recalc_ao_adjustment !== 0
            ? ` ${summary.recalc_ao_adjustment >= 0 ? "+" : "−"} ${formatCurrency(
                Math.abs(summary.recalc_ao_adjustment),
              )}`
            : ""}{" "}
          = <span style={{ color: DPC.gold }}>{formatCurrency(summary.net_payment_adjusted)}</span>
        </p>
      </div>

      <div
        className="mt-3 flex items-center justify-between rounded-lg px-4 py-3 text-white"
        style={{
          background: `linear-gradient(135deg, ${DPC.container}, ${DPC.navyDeep})`,
          borderBottom: `3px solid ${DPC.gold}`,
        }}
      >
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-white/60">
            Net Payment to A&amp;O
          </p>
          <p className={`text-2xl font-bold ${MONO}`}>
            {formatCurrency(summary.net_payment_adjusted)}
          </p>
        </div>
        <Wallet className="h-8 w-8 opacity-40" />
      </div>
    </Panel>
  )
}
