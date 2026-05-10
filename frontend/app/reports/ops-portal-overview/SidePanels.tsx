"use client"

import { Loader2 } from "lucide-react"
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
  return (
    <PanelCard title="Customer Monthly Variance" icon="" loading={isLoading} error={error}>
      <div className="max-h-[260px] overflow-auto">
        <table className="w-full text-xs">
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
                <td className="px-2 py-1 truncate text-[#374151]">{r.customer_name}</td>
                <td className={`px-2 py-1 text-right ${r.volume_var < 0 ? "text-[#DC2626]" : "text-[#374151]"}`}>
                  {fmtCount(r.volume_var)}
                </td>
                <td className={`px-2 py-1 text-right ${r.profit_var < 0 ? "text-[#DC2626]" : "text-[#374151]"}`}>
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
  return (
    <PanelCard title="Customer Monthly Losses" icon="" loading={isLoading} error={error}>
      <div className="max-h-[260px] overflow-auto">
        <table className="w-full text-xs">
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
                <td className="px-2 py-1 truncate text-[#374151]">{r.customer_name}</td>
                <td className="px-2 py-1 text-right text-[#374151]">{fmtCount(r.loss_loads)}</td>
                <td className="px-2 py-1 text-right text-[#DC2626]">{fmtUsdSigned(r.loss_profit)}</td>
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
  return (
    <PanelCard title="Team Monthly Performance" icon="📈" loading={isLoading} error={error}>
      <table className="w-full text-xs">
        <tbody>
          <Row label="Customers"   value={v ? fmtCount(v.customers)   : "—"} />
          <Row label="Lanes"       value={v ? fmtCount(v.lanes)       : "—"} />
          <Row label="Volume"      value={v ? fmtCount(v.volume)      : "—"} />
          <Row label="Revenue"     value={v ? fmtUsd(v.revenue)       : "—"} />
          <Row label="Profit"      value={v ? fmtUsd(v.profit)        : "—"} signed numeric={v?.profit ?? 0} />
          <Row label="Margin P %"  value={v ? fmtPct(v.margin_pct)    : "—"} signed numeric={v?.margin_pct ?? 0} />
          <Row label="Rev. x L."   value={v ? fmtUsd(v.rev_x_l)       : "—"} />
          <Row label="Prf. X L."   value={v ? fmtUsd(v.prof_x_l)      : "—"} signed numeric={v?.prof_x_l ?? 0} />
          <Row label="Team Ut."    value={v ? fmtPct(v.team_ut)       : "—"} />
          <Row label="OTP."        value={v ? fmtPct(v.otp_pct)       : "—"} />
          <Row label="Lates PU"    value={v ? fmtCount(v.lates_pu)    : "—"} />
          <Row label="OTD."        value={v ? fmtPct(v.otd_pct)       : "—"} />
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
  children,
}: {
  title: string
  icon?: string
  loading?: boolean
  error?: unknown
  children: React.ReactNode
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2 text-sm font-semibold text-[#3B82F6]">
        {icon && <span aria-hidden>{icon}</span>}
        <span>{title}</span>
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
}: {
  label: string
  value: string
  signed?: boolean
  numeric?: number
}) {
  const isNeg = signed && (numeric ?? 0) < 0
  return (
    <tr className="border-t border-[#F3F4F6] first:border-t-0">
      <td className="px-1 py-1 text-[#6B7280]">{label}</td>
      <td className={`px-1 py-1 text-right tabular-nums ${isNeg ? "text-[#DC2626]" : "text-[#374151]"}`}>
        {value}
      </td>
    </tr>
  )
}
