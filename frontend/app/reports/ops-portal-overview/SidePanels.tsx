"use client"

import { useState } from "react"
import { Loader2, Plus } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtUsdSigned,
  useOppCustomerLosses,
  useOppCustomerVariance,
  useOppTeamPerformance,
  useOppTeamProjection,
  useOppTeamVariance,
  type OppFilters,
} from "@/lib/ops-portal-overview-api"
import { TeamWeeklyModal } from "./TeamWeeklyModal"

interface Props {
  filters: OppFilters
}

export function SidePanels({ filters }: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <div className="space-y-4">
        <TeamBudgetVariance filters={filters} />
        <CustomerVariance filters={filters} />
        <CustomerLosses filters={filters} />
      </div>
      <div className="space-y-4">
        <TeamPerformance filters={filters} />
        <TeamProjection filters={filters} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// §2 — Team Budget Monthly Variance (inverted single-row table)
// ---------------------------------------------------------------------------

function TeamBudgetVariance({ filters }: { filters: OppFilters }) {
  const { data, isLoading, error } = useOppTeamVariance(filters)
  const v = data?.data
  return (
    <PanelCard title="Team Budget Monthly Variance" icon="📊" loading={isLoading} error={error}>
      <table className="w-full text-xs">
        <tbody>
          <Row label="Customers"  value={v ? String(v.customers) : "—"} signed numeric={v?.customers ?? 0} />
          <Row label="Volume"     value={v ? fmtCount(v.volume_var) : "—"}  signed numeric={v?.volume_var ?? 0} />
          <Row label="Revenue"    value={v ? fmtUsdSigned(v.revenue_var) : "—"} signed numeric={v?.revenue_var ?? 0} />
          <Row label="Profit"     value={v ? fmtUsdSigned(v.profit_var) : "—"}  signed numeric={v?.profit_var ?? 0} />
          <Row label="Margin P %" value={v ? fmtPct(v.margin_var_pct) : "—"} signed numeric={v?.margin_var_pct ?? 0} />
          <Row label="Rev. x L."  value={v ? fmtUsdSigned(v.rev_x_l) : "—"}   signed numeric={v?.rev_x_l ?? 0} />
          <Row label="Prf. X L."  value={v ? fmtUsdSigned(v.prof_x_l) : "—"}  signed numeric={v?.prof_x_l ?? 0} />
        </tbody>
      </table>
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// §3 — Customer Monthly Variance
// ---------------------------------------------------------------------------

function CustomerVariance({ filters }: { filters: OppFilters }) {
  const { data, isLoading, error } = useOppCustomerVariance(filters)
  const rows = data?.data ?? []
  // Bruno round-2 (2026-05-13): no horizontal scroll, vertical scroll OK.
  return (
    <PanelCard title="Customer Monthly Variance" icon="" loading={isLoading} error={error}>
      <div className="max-h-[260px] overflow-x-hidden overflow-y-auto">
        <table className="w-full table-fixed text-xs">
          <colgroup>
            <col className="w-[60%]" />
            <col className="w-[18%]" />
            <col className="w-[22%]" />
          </colgroup>
          <thead className="sticky top-0 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
            <tr>
              <th className="px-2 py-1 text-left">Customer Name</th>
              <th className="px-2 py-1 text-right">Vol</th>
              <th className="px-2 py-1 text-right">Profit</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={3} className="px-2 py-3 text-center text-[#9CA3AF]">No data</td></tr>
            ) : rows.map((r) => (
              <tr key={r.customer_name} className="border-t border-[#F3F4F6]">
                <td className="truncate px-2 py-1 text-[#374151]" title={r.customer_name}>
                  {r.customer_name}
                </td>
                <td className={`px-2 py-1 text-right tabular-nums ${r.volume_var < 0 ? "text-[#DC2626]" : "text-[#374151]"}`}>
                  {fmtCount(r.volume_var)}
                </td>
                <td className={`px-2 py-1 text-right tabular-nums ${r.profit_var < 0 ? "text-[#DC2626]" : "text-[#374151]"}`}>
                  {fmtUsdSigned(r.profit_var)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// §4 — Customer Monthly Losses
// ---------------------------------------------------------------------------

function CustomerLosses({ filters }: { filters: OppFilters }) {
  const { data, isLoading, error } = useOppCustomerLosses(filters)
  const rows = data?.data ?? []
  // Bruno round-2 (2026-05-13): no horizontal scroll, vertical scroll OK.
  return (
    <PanelCard title="Customer Monthly Losses" icon="" loading={isLoading} error={error}>
      <div className="max-h-[260px] overflow-x-hidden overflow-y-auto">
        <table className="w-full table-fixed text-xs">
          <colgroup>
            <col className="w-[60%]" />
            <col className="w-[18%]" />
            <col className="w-[22%]" />
          </colgroup>
          <thead className="sticky top-0 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
            <tr>
              <th className="px-2 py-1 text-left">Customer Name</th>
              <th className="px-2 py-1 text-right">Vol</th>
              <th className="px-2 py-1 text-right">Profit</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={3} className="px-2 py-3 text-center text-[#9CA3AF]">No losses</td></tr>
            ) : rows.map((r) => (
              <tr key={r.customer_name} className="border-t border-[#F3F4F6]">
                <td className="truncate px-2 py-1 text-[#374151]" title={r.customer_name}>
                  {r.customer_name}
                </td>
                <td className="px-2 py-1 text-right tabular-nums text-[#374151]">{fmtCount(r.loss_loads)}</td>
                <td className="px-2 py-1 text-right tabular-nums text-[#DC2626]">{fmtUsdSigned(r.loss_profit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// §5 — Team Monthly Performance
// ---------------------------------------------------------------------------

function TeamPerformance({ filters }: { filters: OppFilters }) {
  const { data, isLoading, error } = useOppTeamPerformance(filters)
  const v = data?.data
  const [weeklyOpen, setWeeklyOpen] = useState(false)
  // Bruno round-2 (2026-05-13): OTP/OTD coloured bands + highlight Volume/Profit/Margin.
  // Bruno R4 (2026-05-27): "+" opens the Team Weekly Performance modal.
  return (
    <PanelCard
      title="Team Monthly Performance"
      icon="📈"
      loading={isLoading}
      error={error}
      action={
        <button
          type="button"
          onClick={() => setWeeklyOpen(true)}
          title="Team Weekly Performance — last 5 weeks"
          className="flex h-5 w-5 items-center justify-center rounded border border-[#BFDBFE] bg-white text-[#2563EB] hover:bg-[#EFF6FF]"
          aria-label="Open Team Weekly Performance"
        >
          <Plus className="h-3 w-3" />
        </button>
      }
    >
      <table className="w-full text-xs">
        <tbody>
          <Row label="Customers"   value={v ? fmtCount(v.customers)   : "—"} />
          <Row label="Lanes"       value={v ? fmtCount(v.lanes)       : "—"} />
          <Row label="Volume"      value={v ? fmtCount(v.volume)      : "—"} highlight />
          <Row label="Revenue"     value={v ? fmtUsd(v.revenue)       : "—"} />
          <Row label="Profit"      value={v ? fmtUsd(v.profit)        : "—"} signed numeric={v?.profit ?? 0} highlight />
          <Row label="Margin P %"  value={v ? fmtPct(v.margin_pct)    : "—"} signed numeric={v?.margin_pct ?? 0} highlight />
          <Row label="Rev. x L."   value={v ? fmtUsd(v.rev_x_l)       : "—"} />
          <Row label="Prf. X L."   value={v ? fmtUsd(v.prof_x_l)      : "—"} signed numeric={v?.prof_x_l ?? 0} />
          <Row label="Team Ut."    value={v ? fmtPct(v.team_ut)       : "—"} />
          <Row label="OTP."        value={v ? fmtPct(v.otp_pct)       : "—"} bandPct={v?.otp_pct} />
          <Row label="Lates PU"    value={v ? fmtCount(v.lates_pu)    : "—"} />
          <Row label="OTD."        value={v ? fmtPct(v.otd_pct)       : "—"} bandPct={v?.otd_pct} />
          <Row label="Lates DEL."  value={v ? fmtCount(v.lates_del)   : "—"} />
          <Row label="Savings."    value={v ? fmtUsd(v.savings)       : "—"} />
          <Row label="Over Pay"    value={v ? fmtUsd(v.over_pay)      : "—"} signed numeric={v?.over_pay ?? 0} />
          <Row label="Net Savings" value={v ? fmtUsdSigned(v.net_savings) : "—"} signed numeric={v?.net_savings ?? 0} />
          <Row label="Loads w/ Loss." value={v ? fmtCount(v.loss_loads) : "—"} />
          <Row label="Profit Loss" value={v ? fmtUsdSigned(v.profit_loss) : "—"} signed numeric={v?.profit_loss ?? 0} />
          <Row label="Cust. Attrition %" value={v ? fmtPct(v.cust_attr_pct) : "—"} />
          <Row label="Lane Attrition %" value={v ? fmtPct(v.lane_attr_pct) : "—"} />
        </tbody>
      </table>
      {weeklyOpen && <TeamWeeklyModal filters={filters} onClose={() => setWeeklyOpen(false)} />}
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// §6 — Team Monthly Projection
// ---------------------------------------------------------------------------

function TeamProjection({ filters }: { filters: OppFilters }) {
  const cf = { team: filters.team, customer: filters.customer, loadType: filters.loadType }
  const { data, isLoading, error } = useOppTeamProjection(cf)
  const v = data?.data
  return (
    <PanelCard title="Team Monthly Projection" icon="🎯" loading={isLoading} error={error}>
      <table className="w-full text-xs">
        <tbody>
          <Row label="Avg. Vol x Day"  value={v ? fmtCount(v.avg_vol_day)  : "—"} />
          <Row label="Avg. Rev. x Day" value={v ? fmtUsd(v.avg_rev_day)    : "—"} />
          <Row label="Avg. Prof. x Day" value={v ? fmtUsd(v.avg_prof_day)  : "—"} signed numeric={v?.avg_prof_day ?? 0} />
          <tr><td colSpan={2} className="py-1"></td></tr>
          <Row label="Pending Days"    value={v ? fmtCount(v.pending_workdays) : "—"} />
          <tr><td colSpan={2} className="py-1"></td></tr>
          <Row label="Proj. Volume"    value={v ? fmtCount(v.proj_volume)  : "—"} />
          <Row label="Proj. Revenue"   value={v ? fmtUsd(v.proj_revenue)   : "—"} />
          <Row label="Proj. Profit"    value={v ? fmtUsd(v.proj_profit)    : "—"} signed numeric={v?.proj_profit ?? 0} />
          <Row label="Proj. Margin P %" value={v ? fmtPct(v.proj_margin_pct) : "—"} signed numeric={v?.proj_margin_pct ?? 0} />
          <Row label="Proj. Rev. x L." value={v ? fmtUsd(v.proj_rev_x_l)   : "—"} />
          <Row label="Proj. Prf. X L." value={v ? fmtUsd(v.proj_prof_x_l)  : "—"} signed numeric={v?.proj_prof_x_l ?? 0} />
          <Row label="Proj. Team Ut."  value={v ? fmtPct(v.proj_team_ut)   : "—"} />
        </tbody>
      </table>
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

function PanelCard({
  title,
  icon,
  loading,
  error,
  action,
  children,
}: {
  title: string
  icon?: string
  loading?: boolean
  error?: unknown
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2 text-sm font-semibold text-[#3B82F6]">
        {icon && <span aria-hidden>{icon}</span>}
        <span>{title}</span>
        {action && <span className="ml-1">{action}</span>}
        {loading && <Loader2 className="ml-auto h-3 w-3 animate-spin text-[#6B7280]" />}
      </div>
      {error ? (
        <div className="px-3 py-3 text-xs text-[#DC2626]">Failed to load</div>
      ) : (
        <div className="px-3 py-2">{children}</div>
      )}
    </section>
  )
}

function Row({
  label,
  value,
  signed,
  numeric,
  highlight,
  bandPct,
}: {
  label: string
  value: string
  signed?: boolean
  numeric?: number
  /** Bold + soft background — Bruno round-2 marker for Volume/Profit/Margin. */
  highlight?: boolean
  /**
   * OTP/OTD coloured-band swatch (Bruno round-2): >=95.5% green,
   * >=93% & <95.5% yellow, <93% red. Pass the percentage value.
   */
  bandPct?: number
}) {
  const isNeg = signed && (numeric ?? 0) < 0
  const bandCls =
    bandPct === undefined
      ? ""
      : bandPct >= 95.5
      ? "bg-[#DCFCE7] text-[#166534]"
      : bandPct >= 93
      ? "bg-[#FEF9C3] text-[#854D0E]"
      : "bg-[#FEE2E2] text-[#991B1B]"
  return (
    <tr className={`border-t border-[#F3F4F6] first:border-t-0 ${highlight ? "bg-[#F0F9FF]" : ""}`}>
      <td className={`px-1 py-1 ${highlight ? "font-semibold text-[#1B3A5C]" : "text-[#6B7280]"}`}>
        {label}
      </td>
      <td className="px-1 py-1 text-right tabular-nums">
        {bandPct !== undefined ? (
          <span className={`rounded px-1.5 py-0.5 font-semibold ${bandCls}`}>{value}</span>
        ) : (
          <span
            className={`${
              isNeg ? "text-[#DC2626]" : "text-[#374151]"
            } ${highlight ? "font-bold text-[#1B3A5C]" : ""}`}
          >
            {value}
          </span>
        )}
      </td>
    </tr>
  )
}
