"use client"

import { useEffect, useMemo, useState } from "react"
import { ArrowDown, ArrowUp, Loader2, Maximize2, X } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtUsdSigned,
  useOppCustomerLosses,
  useOppCustomerNotBilled,
  useOppCustomerVariance,
  useOppTeamPerformance,
  useOppTeamProjection,
  useOppTeamProjectionByTeam,
  useOppTeamProjectionWeekly,
  useOppTeamVariance,
  useOppTeamVarianceByTeam,
  useOppTeamVarianceWeekly,
  type OppCustomerLoss,
  type OppCustomerNotBilledRow,
  type OppCustomerNotBilledTotals,
  type OppCustomerVariance,
  type OppFilters,
  type OppTeamProjection,
  type OppTeamVariance,
} from "@/lib/ops-portal-overview-api"
import { TeamWeeklyModal } from "./TeamWeeklyModal"
import { TeamMonthlyModal } from "./TeamMonthlyModal"
import { MetricMatrixModal, type MatrixCell, type MatrixRow } from "./MetricMatrixModal"

interface Props {
  filters: OppFilters
  /**
   * R9 (Bruno): when present, customer-name cells in the Customer Variance /
   * Losses panels become clickable links that drill to that customer.
   */
  onPickCustomer?: (customer: string) => void
  /**
   * Bruno (2026-06-26): per-team CORP copies (T1–T4) lock to one team, so the
   * cross-team "Team" breakdown button in Team Monthly Performance is hidden.
   */
  lockedTeam?: string
}

export function SidePanels({ filters, onPickCustomer, lockedTeam }: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <div className="space-y-4">
        <TeamBudgetVariance filters={filters} lockedTeam={lockedTeam} />
        <CustomerVariance filters={filters} onPickCustomer={onPickCustomer} />
        <CustomerLosses filters={filters} onPickCustomer={onPickCustomer} />
        <CustomerNotBilled filters={filters} />
      </div>
      <div className="space-y-4">
        <TeamPerformance filters={filters} lockedTeam={lockedTeam} />
        <TeamProjection filters={filters} lockedTeam={lockedTeam} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// §2 — Team Budget Monthly Variance (inverted single-row table)
// ---------------------------------------------------------------------------

function TeamBudgetVariance({ filters, lockedTeam }: { filters: OppFilters; lockedTeam?: string }) {
  const { data, isLoading, error } = useOppTeamVariance(filters)
  const v = data?.data
  // Bruno (PDF 2026-07-13): Week / Team break-out modals.
  const [weekOpen, setWeekOpen] = useState(false)
  const [teamOpen, setTeamOpen] = useState(false)
  return (
    <PanelCard
      title="Team Budget Monthly Variance"
      icon="📊"
      loading={isLoading}
      error={error}
      action={
        <WeekTeamButtons
          onWeek={() => setWeekOpen(true)}
          onTeam={() => setTeamOpen(true)}
          lockedTeam={lockedTeam}
        />
      }
    >
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
      {weekOpen && <VarianceWeekModal filters={filters} onClose={() => setWeekOpen(false)} />}
      {teamOpen && <VarianceTeamModal filters={filters} onClose={() => setTeamOpen(false)} />}
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// §3 — Customer Monthly Variance
// ---------------------------------------------------------------------------

function CustomerVariance({ filters, onPickCustomer }: { filters: OppFilters; onPickCustomer?: (c: string) => void }) {
  const { data, isLoading, error } = useOppCustomerVariance(filters)
  const raw = useMemo(() => data?.data ?? [], [data])
  const [expanded, setExpanded] = useState(false)
  // Bruno R5 (#14): sortable on every column. Default = profit variance asc
  // (most-negative first), matching the prior fixed order.
  const { rows, sortKey, sortDir, onSort } = useMiniSort<OppCustomerVariance, "name" | "vol" | "profit">(raw, {
    name: (r) => (r.customer_name || "").toUpperCase(),
    vol: (r) => r.volume_var,
    profit: (r) => r.profit_var,
  }, "profit", "asc")
  const renderTable = () => (
    <table className="w-full table-fixed text-xs">
      <colgroup>
        <col className="w-[60%]" />
        <col className="w-[18%]" />
        <col className="w-[22%]" />
      </colgroup>
      <thead className="sticky top-0 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
        <tr>
          <MiniTh k="name" align="left" sortKey={sortKey} dir={sortDir} onSort={onSort}>Customer Name</MiniTh>
          <MiniTh k="vol" align="right" sortKey={sortKey} dir={sortDir} onSort={onSort}>Vol</MiniTh>
          <MiniTh k="profit" align="right" sortKey={sortKey} dir={sortDir} onSort={onSort}>Profit</MiniTh>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr><td colSpan={3} className="px-2 py-3 text-center text-[#9CA3AF]">No data</td></tr>
        ) : rows.map((r) => (
          <tr key={r.customer_name} className="border-t border-[#F3F4F6]">
            <td className="truncate px-2 py-1 text-[#374151]" title={r.customer_name}>
              <CustomerNameCell name={r.customer_name} onPick={onPickCustomer} />
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
  )
  return (
    <PanelCard
      title="Customer Monthly Variance"
      icon=""
      loading={isLoading}
      error={error}
      leadingAction={<ExpandButton label="Customer Monthly Variance" onClick={() => setExpanded(true)} />}
    >
      <div className="max-h-[260px] overflow-x-hidden overflow-y-auto">{renderTable()}</div>
      {expanded && (
        <ExpandModal title="Customer Monthly Variance" onClose={() => setExpanded(false)}>
          {renderTable()}
        </ExpandModal>
      )}
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// §4 — Customer Monthly Losses
// ---------------------------------------------------------------------------

function CustomerLosses({ filters, onPickCustomer }: { filters: OppFilters; onPickCustomer?: (c: string) => void }) {
  const { data, isLoading, error } = useOppCustomerLosses(filters)
  const raw = useMemo(() => data?.data ?? [], [data])
  const [expanded, setExpanded] = useState(false)
  // Bruno R5 (#15): sortable on every column. Default = loss profit asc
  // (biggest loss first), matching the prior fixed order.
  const { rows, sortKey, sortDir, onSort } = useMiniSort<OppCustomerLoss, "name" | "vol" | "profit">(raw, {
    name: (r) => (r.customer_name || "").toUpperCase(),
    vol: (r) => r.loss_loads,
    profit: (r) => r.loss_profit,
  }, "profit", "asc")
  const renderTable = () => (
    <table className="w-full table-fixed text-xs">
      <colgroup>
        <col className="w-[60%]" />
        <col className="w-[18%]" />
        <col className="w-[22%]" />
      </colgroup>
      <thead className="sticky top-0 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
        <tr>
          <MiniTh k="name" align="left" sortKey={sortKey} dir={sortDir} onSort={onSort}>Customer Name</MiniTh>
          <MiniTh k="vol" align="right" sortKey={sortKey} dir={sortDir} onSort={onSort}>Vol</MiniTh>
          <MiniTh k="profit" align="right" sortKey={sortKey} dir={sortDir} onSort={onSort}>Profit</MiniTh>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr><td colSpan={3} className="px-2 py-3 text-center text-[#9CA3AF]">No losses</td></tr>
        ) : rows.map((r) => (
          <tr key={r.customer_name} className="border-t border-[#F3F4F6]">
            <td className="truncate px-2 py-1 text-[#374151]" title={r.customer_name}>
              <CustomerNameCell name={r.customer_name} onPick={onPickCustomer} />
            </td>
            <td className="px-2 py-1 text-right tabular-nums text-[#374151]">{fmtCount(r.loss_loads)}</td>
            <td className="px-2 py-1 text-right tabular-nums text-[#DC2626]">{fmtUsdSigned(r.loss_profit)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
  return (
    <PanelCard
      title="Customer Monthly Losses"
      icon=""
      loading={isLoading}
      error={error}
      leadingAction={<ExpandButton label="Customer Monthly Losses" onClick={() => setExpanded(true)} />}
    >
      <div className="max-h-[180px] overflow-x-hidden overflow-y-auto">{renderTable()}</div>
      {expanded && (
        <ExpandModal title="Customer Monthly Losses" onClose={() => setExpanded(false)}>
          {renderTable()}
        </ExpandModal>
      )}
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// §4b — Not Billed (Bruno R14) — customers with delivered-but-not-billed loads.
// ---------------------------------------------------------------------------

function CustomerNotBilled({ filters }: { filters: OppFilters }) {
  const q = useOppCustomerNotBilled(filters)
  const totals = q.data?.meta?.totals as OppCustomerNotBilledTotals | undefined
  const raw = useMemo(() => q.data?.data ?? [], [q.data])
  // Default = revenue desc (biggest un-billed revenue first).
  const { rows: sorted, sortKey, sortDir, onSort } = useMiniSort<OppCustomerNotBilledRow, "name" | "loads" | "revenue">(raw, {
    name: (r) => (r.customer_name || "").toUpperCase(),
    loads: (r) => r.loads,
    revenue: (r) => r.revenue,
  }, "revenue", "desc")
  return (
    <PanelCard title="Not Billed" icon="🧾" loading={q.isLoading} error={q.error}>
      <div className="max-h-[180px] overflow-x-hidden overflow-y-auto">
        <table className="w-full table-fixed text-xs">
          <colgroup>
            <col className="w-[60%]" />
            <col className="w-[18%]" />
            <col className="w-[22%]" />
          </colgroup>
          <thead className="sticky top-0 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
            <tr>
              <MiniTh k="name" align="left" sortKey={sortKey} dir={sortDir} onSort={onSort}>Customer</MiniTh>
              <MiniTh k="loads" align="right" sortKey={sortKey} dir={sortDir} onSort={onSort}>Loads</MiniTh>
              <MiniTh k="revenue" align="right" sortKey={sortKey} dir={sortDir} onSort={onSort}>Revenue</MiniTh>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr><td colSpan={3} className="px-2 py-3 text-center text-[#9CA3AF]">No data</td></tr>
            ) : sorted.map((r) => (
              <tr key={r.customer_name} className="border-t border-[#F3F4F6]">
                <td className="truncate px-2 py-1 text-[#374151]" title={r.customer_name}>{r.customer_name}</td>
                <td className="px-2 py-1 text-right tabular-nums text-[#374151]">{fmtCount(r.loads)}</td>
                <td className="px-2 py-1 text-right tabular-nums text-[#374151]">{fmtUsd(r.revenue)}</td>
              </tr>
            ))}
          </tbody>
          {totals && (
            <tfoot className="sticky bottom-0 bg-[#F9FAFB]">
              <tr className="border-t border-[#E5E7EB] font-semibold text-[#1B3A5C]">
                <td className="px-2 py-1">Total</td>
                <td className="px-2 py-1 text-right tabular-nums">{fmtCount(totals.loads)}</td>
                <td className="px-2 py-1 text-right tabular-nums">{fmtUsd(totals.revenue)}</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// §5 — Team Monthly Performance
// ---------------------------------------------------------------------------

function TeamPerformance({ filters, lockedTeam }: { filters: OppFilters; lockedTeam?: string }) {
  const { data, isLoading, error } = useOppTeamPerformance(filters)
  const v = data?.data
  const [weeklyOpen, setWeeklyOpen] = useState(false)
  const [monthlyOpen, setMonthlyOpen] = useState(false)
  // Bruno round-2 (2026-05-13): OTP/OTD coloured bands + highlight Volume/Profit/Margin.
  // Bruno R4 (2026-05-27): "+" opens the Team Weekly Performance modal.
  // Bruno R6/R7: "+" relabelled "Week"; new "Team" button opens the monthly modal.
  // R12: Cost x Load = total_cost / volume (guard div-by-zero).
  const costXLoad = v && v.volume ? v.total_cost / v.volume : 0
  return (
    <PanelCard
      title="Team Monthly Performance"
      icon="📈"
      loading={isLoading}
      error={error}
      action={
        <span className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setWeeklyOpen(true)}
            title="Team Weekly Performance — last 5 weeks"
            className="flex h-5 items-center justify-center rounded border border-[#BFDBFE] bg-white px-1.5 text-[10px] font-semibold text-[#2563EB] hover:bg-[#EFF6FF]"
            aria-label="Open Team Weekly Performance"
          >
            Week
          </button>
          {/* Bruno (2026-06-26): cross-team breakdown is meaningless on the
              single-team CORP copies (T1–T4) — hide the button when locked. */}
          {!lockedTeam && (
            <button
              type="button"
              onClick={() => setMonthlyOpen(true)}
              title="Team Monthly Performance — by team"
              className="flex h-5 items-center justify-center rounded border border-[#BFDBFE] bg-white px-1.5 text-[10px] font-semibold text-[#2563EB] hover:bg-[#EFF6FF]"
              aria-label="Open Team Monthly Performance"
            >
              Team
            </button>
          )}
        </span>
      }
    >
      <table className="w-full text-xs">
        <tbody>
          <Row label="Customers"   value={v ? fmtCount(v.customers)   : "—"} />
          <Row label="Lanes"       value={v ? fmtCount(v.lanes)       : "—"} />
          <Row label="Volume"      value={v ? fmtCount(v.volume)      : "—"} highlight />
          <Row label="Revenue"     value={v ? fmtUsd(v.revenue)       : "—"} />
          <Row label="Total Cost"  value={v ? fmtUsd(v.total_cost)    : "—"} />
          <Row label="Profit"      value={v ? fmtUsd(v.profit)        : "—"} signed numeric={v?.profit ?? 0} highlight />
          <Row label="Margin P %"  value={v ? fmtPct(v.margin_pct)    : "—"} signed numeric={v?.margin_pct ?? 0} highlight />
          <Row label="Rev. x L."   value={v ? fmtUsd(v.rev_x_l)       : "—"} />
          <Row label="Prf. X L."   value={v ? fmtUsd(v.prof_x_l)      : "—"} signed numeric={v?.prof_x_l ?? 0} />
          <Row label="Cost x Load" value={v ? fmtUsd(costXLoad)       : "—"} />
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
          <Row label="AVG Days (Billed)" value={v ? v.avg_days_billed.toFixed(1) : "—"} />
          <Row label="AVG Days (Not Billed)" value={v ? v.avg_days_not_billed.toFixed(1) : "—"} />
          <Row label="% Del vs Bill" value={v ? fmtPct(v.pct_del_bill) : "—"} />
          <Row label="Cust. Attrition %" value={v ? fmtPct(v.cust_attr_pct) : "—"} />
          <Row label="Lane Attrition %" value={v ? fmtPct(v.lane_attr_pct) : "—"} />
        </tbody>
      </table>
      {weeklyOpen && <TeamWeeklyModal filters={filters} onClose={() => setWeeklyOpen(false)} />}
      {monthlyOpen && <TeamMonthlyModal filters={filters} onClose={() => setMonthlyOpen(false)} />}
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// §6 — Team Monthly Projection
// ---------------------------------------------------------------------------

function TeamProjection({ filters, lockedTeam }: { filters: OppFilters; lockedTeam?: string }) {
  const cf = { team: filters.team, customer: filters.customer, loadType: filters.loadType, lanes: filters.lanes, excludeLanes: filters.excludeLanes }
  const { data, isLoading, error } = useOppTeamProjection(cf)
  const v = data?.data
  // Bruno (PDF 2026-07-13): Week / Team break-out modals.
  const [weekOpen, setWeekOpen] = useState(false)
  const [teamOpen, setTeamOpen] = useState(false)
  return (
    <PanelCard
      title="Team Monthly Projection"
      icon="🎯"
      loading={isLoading}
      error={error}
      action={
        <WeekTeamButtons
          onWeek={() => setWeekOpen(true)}
          onTeam={() => setTeamOpen(true)}
          lockedTeam={lockedTeam}
        />
      }
    >
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
      {weekOpen && <ProjectionWeekModal filters={filters} onClose={() => setWeekOpen(false)} />}
      {teamOpen && <ProjectionTeamModal filters={filters} onClose={() => setTeamOpen(false)} />}
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

export function PanelCard({
  title,
  icon,
  loading,
  error,
  action,
  leadingAction,
  children,
}: {
  title: string
  icon?: string
  loading?: boolean
  error?: unknown
  action?: React.ReactNode
  /** Bruno R11 — small control rendered at the top-left of the header (e.g. expand). */
  leadingAction?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2 text-sm font-semibold text-[#3B82F6]">
        {leadingAction}
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

export function Row({
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

// ---------------------------------------------------------------------------
// R9 — clickable customer-name cell. Looks like a link only when a drill
// handler is provided; otherwise renders plain text (preserves the old look).
// ---------------------------------------------------------------------------

function CustomerNameCell({ name, onPick }: { name: string; onPick?: (c: string) => void }) {
  if (!onPick) return <>{name}</>
  return (
    <button
      type="button"
      onClick={() => onPick(name)}
      className="truncate text-left text-[#2563EB] hover:underline"
      title={`Drill to ${name}`}
    >
      {name}
    </button>
  )
}

// ---------------------------------------------------------------------------
// R11 (Bruno) — top-left expand button + modal rendering the uncapped table.
// ---------------------------------------------------------------------------

function ExpandButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`Expand ${label}`}
      aria-label={`Expand ${label}`}
      className="flex h-5 w-5 items-center justify-center rounded border border-[#BFDBFE] bg-white text-[#2563EB] hover:bg-[#EFF6FF]"
    >
      <Maximize2 className="h-3.5 w-3.5" />
    </button>
  )
}

function ExpandModal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#E5E7EB] bg-[#F9FAFB] px-4 py-2 text-sm font-semibold text-[#1B3A5C]">
          <span>{title}</span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-[#6B7280] hover:bg-[#E5E7EB]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="overflow-auto px-4 py-3">{children}</div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mini sortable-table helpers (Bruno R5 #14/#15) — reused by the two Customer
// panels. Client-side: the lists are already capped server-side at 50 rows.
// ---------------------------------------------------------------------------

type MiniDir = "asc" | "desc"

function useMiniSort<T, K extends string>(
  rows: T[],
  accessors: Record<K, (r: T) => number | string>,
  initialKey: K,
  initialDir: MiniDir,
) {
  const [sortKey, setSortKey] = useState<K>(initialKey)
  const [sortDir, setSortDir] = useState<MiniDir>(initialDir)
  const sorted = useMemo(() => {
    const acc = accessors[sortKey]
    if (!acc) return rows
    const mult = sortDir === "asc" ? 1 : -1
    return [...rows].sort((a, b) => {
      const va = acc(a)
      const vb = acc(b)
      if (typeof va === "string" || typeof vb === "string") {
        return String(va).localeCompare(String(vb)) * mult
      }
      return ((va as number) - (vb as number)) * mult
    })
    // accessors is a stable literal per render site; key/dir/rows drive it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sortKey, sortDir])
  const onSort = (k: K) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(k)
      // Text col → asc, numeric col → desc on first click.
      setSortDir(k === "name" ? "asc" : "desc")
    }
  }
  return { rows: sorted, sortKey, sortDir, onSort }
}

function MiniTh<K extends string>({
  children,
  k,
  align,
  sortKey,
  dir,
  onSort,
}: {
  children: React.ReactNode
  k: K
  align: "left" | "right"
  sortKey: K
  dir: MiniDir
  onSort: (k: K) => void
}) {
  const active = sortKey === k
  const cls = align === "right" ? "text-right" : "text-left"
  const justify = align === "right" ? "justify-end" : "justify-start"
  return (
    <th className={`px-2 py-1 ${cls}`}>
      <button
        type="button"
        onClick={() => onSort(k)}
        className={`inline-flex w-full items-center gap-1 ${justify} ${
          active ? "font-bold text-[#1B3A5C]" : "hover:text-[#374151]"
        }`}
      >
        {children}
        {active && (dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  )
}

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-07-13) — Week / Team break-out modals for the Team Budget
// Variance and Team Monthly Projection panels.
// ---------------------------------------------------------------------------

function WeekTeamButtons({
  onWeek,
  onTeam,
  lockedTeam,
}: {
  onWeek: () => void
  onTeam: () => void
  lockedTeam?: string
}) {
  const btn =
    "flex h-5 items-center justify-center rounded border border-[#BFDBFE] bg-white px-1.5 text-[10px] font-semibold text-[#2563EB] hover:bg-[#EFF6FF]"
  return (
    <span className="flex items-center gap-1">
      <button type="button" onClick={onWeek} className={btn} title="Break out by the last 5 weeks">
        Week
      </button>
      {/* Cross-team breakdown is meaningless on the single-team CORP copies. */}
      {!lockedTeam && (
        <button type="button" onClick={onTeam} className={btn} title="Break out by team">
          Team
        </button>
      )}
    </span>
  )
}

// Signed colour for a variance/projection numeric cell.
function signCls(n: number): string {
  return n < 0 ? "text-[#DC2626]" : "text-[#374151]"
}

// "% of total" suffix for a team column's additive cell (blank when total is 0).
function conc(val: number, total: number): string {
  if (!total) return ""
  return `  ${((val / total) * 100).toFixed(2)}%`
}

function VarianceWeekModal({ filters, onClose }: { filters: OppFilters; onClose: () => void }) {
  const { data, isLoading, error } = useOppTeamVarianceWeekly(filters, true)
  const weeks = data?.data?.weeks ?? []
  const columns = weeks.map((w) => w.label)
  const num = (get: (w: OppTeamVariance) => number, fmt: (n: number) => string, signed = true): MatrixCell[] =>
    weeks.map((w) => {
      const v = get(w)
      return { text: fmt(v), className: signed ? signCls(v) : undefined }
    })
  const rows: MatrixRow[] = [
    { label: "Customers",  cells: num((w) => w.customers, fmtCount, false) },
    { label: "Volume",     cells: num((w) => w.volume_var, fmtCount), highlight: true },
    { label: "Revenue",    cells: num((w) => w.revenue_var, fmtUsdSigned) },
    { label: "Profit",     cells: num((w) => w.profit_var, fmtUsdSigned), highlight: true },
    { label: "Margin P %", cells: num((w) => w.margin_var_pct, fmtPct) },
    { label: "Rev. x L.",  cells: num((w) => w.rev_x_l, fmtUsdSigned) },
    { label: "Prf. X L.",  cells: num((w) => w.prof_x_l, fmtUsdSigned) },
  ]
  return (
    <MetricMatrixModal
      title="Team Budget Monthly Variance"
      subtitle="last 5 weeks (Mon–Sun)"
      icon="📊"
      columns={columns}
      rows={rows}
      loading={isLoading}
      error={error}
      onClose={onClose}
    />
  )
}

function VarianceTeamModal({ filters, onClose }: { filters: OppFilters; onClose: () => void }) {
  const { data, isLoading, error } = useOppTeamVarianceByTeam(filters, true)
  const total = data?.data?.total
  const teams = data?.data?.teams ?? []
  const columns = ["Total", ...teams.map((t) => t.team_id)]
  const num = (
    get: (v: OppTeamVariance) => number,
    fmt: (n: number) => string,
    { signed = true, showConc = false }: { signed?: boolean; showConc?: boolean } = {},
  ): MatrixCell[] => {
    const tv = total ? get(total) : 0
    const cells: MatrixCell[] = [
      { text: total ? fmt(tv) : "—", className: signed ? signCls(tv) : undefined },
    ]
    for (const t of teams) {
      const v = get(t)
      cells.push({ text: fmt(v) + (showConc ? conc(v, tv) : ""), className: signed ? signCls(v) : undefined })
    }
    return cells
  }
  const rows: MatrixRow[] = [
    { label: "Customers",  cells: num((v) => v.customers, fmtCount, { signed: false, showConc: true }) },
    { label: "Volume",     cells: num((v) => v.volume_var, fmtCount, { showConc: true }), highlight: true },
    { label: "Revenue",    cells: num((v) => v.revenue_var, fmtUsdSigned, { showConc: true }) },
    { label: "Profit",     cells: num((v) => v.profit_var, fmtUsdSigned, { showConc: true }), highlight: true },
    { label: "Margin P %", cells: num((v) => v.margin_var_pct, fmtPct) },
    { label: "Rev. x L.",  cells: num((v) => v.rev_x_l, fmtUsdSigned) },
    { label: "Prf. X L.",  cells: num((v) => v.prof_x_l, fmtUsdSigned) },
  ]
  return (
    <MetricMatrixModal
      title="Team Budget Monthly Variance"
      subtitle="by team"
      icon="📊"
      columns={columns}
      rows={rows}
      loading={isLoading}
      error={error}
      onClose={onClose}
    />
  )
}

function projectionCf(filters: OppFilters) {
  return {
    team: filters.team,
    customer: filters.customer,
    loadType: filters.loadType,
    lanes: filters.lanes,
    excludeLanes: filters.excludeLanes,
  }
}

function ProjectionWeekModal({ filters, onClose }: { filters: OppFilters; onClose: () => void }) {
  const { data, isLoading, error } = useOppTeamProjectionWeekly(projectionCf(filters), true)
  const weeks = data?.data?.weeks ?? []
  const columns = weeks.map((w) => w.label)
  const num = (get: (w: (typeof weeks)[number]) => number, fmt: (n: number) => string, signed = false): MatrixCell[] =>
    weeks.map((w) => {
      const v = get(w)
      return { text: fmt(v), className: signed ? signCls(v) : undefined }
    })
  const rows: MatrixRow[] = [
    { label: "Avg. Vol x Day",   cells: num((w) => w.avg_vol_day, fmtCount) },
    { label: "Avg. Rev. x Day",  cells: num((w) => w.avg_rev_day, fmtUsd) },
    { label: "Avg. Prof. x Day", cells: num((w) => w.avg_prof_day, fmtUsdSigned, true) },
    { label: "Days Worked",      cells: num((w) => w.pending_workdays, fmtCount) },
    { label: "Volume",           cells: num((w) => w.proj_volume, fmtCount), highlight: true },
    { label: "Revenue",          cells: num((w) => w.proj_revenue, fmtUsd) },
    { label: "Profit",           cells: num((w) => w.proj_profit, fmtUsdSigned, true), highlight: true },
    { label: "Margin P %",       cells: num((w) => w.proj_margin_pct, fmtPct, true) },
    { label: "Rev. x L.",        cells: num((w) => w.proj_rev_x_l, fmtUsd) },
    { label: "Prf. X L.",        cells: num((w) => w.proj_prof_x_l, fmtUsdSigned, true) },
    { label: "Team Ut.",         cells: num((w) => w.proj_team_ut, fmtPct) },
  ]
  return (
    <MetricMatrixModal
      title="Team Monthly Projection"
      subtitle="last 5 weeks (Mon–Sun) · weekly actuals"
      icon="🎯"
      columns={columns}
      rows={rows}
      loading={isLoading}
      error={error}
      onClose={onClose}
    />
  )
}

function ProjectionTeamModal({ filters, onClose }: { filters: OppFilters; onClose: () => void }) {
  const { data, isLoading, error } = useOppTeamProjectionByTeam(projectionCf(filters), true)
  const total = data?.data?.total
  const teams = data?.data?.teams ?? []
  const columns = ["Total", ...teams.map((t) => t.team_id)]
  const num = (
    get: (v: OppTeamProjection) => number,
    fmt: (n: number) => string,
    { signed = false, showConc = false }: { signed?: boolean; showConc?: boolean } = {},
  ): MatrixCell[] => {
    const tv = total ? get(total) : 0
    const cells: MatrixCell[] = [
      { text: total ? fmt(tv) : "—", className: signed ? signCls(tv) : undefined },
    ]
    for (const t of teams) {
      const v = get(t)
      cells.push({ text: fmt(v) + (showConc ? conc(v, tv) : ""), className: signed ? signCls(v) : undefined })
    }
    return cells
  }
  const rows: MatrixRow[] = [
    { label: "Avg. Vol x Day",   cells: num((v) => v.avg_vol_day, fmtCount, { showConc: true }) },
    { label: "Avg. Rev. x Day",  cells: num((v) => v.avg_rev_day, fmtUsd, { showConc: true }) },
    { label: "Avg. Prof. x Day", cells: num((v) => v.avg_prof_day, fmtUsdSigned, { signed: true, showConc: true }) },
    { label: "Pending Days",     cells: num((v) => v.pending_workdays, fmtCount) },
    { label: "Proj. Volume",     cells: num((v) => v.proj_volume, fmtCount, { showConc: true }), highlight: true },
    { label: "Proj. Revenue",    cells: num((v) => v.proj_revenue, fmtUsd, { showConc: true }) },
    { label: "Proj. Profit",     cells: num((v) => v.proj_profit, fmtUsdSigned, { signed: true, showConc: true }), highlight: true },
    { label: "Proj. Margin P %", cells: num((v) => v.proj_margin_pct, fmtPct, { signed: true }) },
    { label: "Proj. Rev. x L.",  cells: num((v) => v.proj_rev_x_l, fmtUsd) },
    { label: "Proj. Prf. X L.",  cells: num((v) => v.proj_prof_x_l, fmtUsdSigned, { signed: true }) },
    { label: "Proj. Team Ut.",   cells: num((v) => v.proj_team_ut, fmtPct) },
  ]
  return (
    <MetricMatrixModal
      title="Team Monthly Projection"
      subtitle="by team"
      icon="🎯"
      columns={columns}
      rows={rows}
      loading={isLoading}
      error={error}
      onClose={onClose}
    />
  )
}
