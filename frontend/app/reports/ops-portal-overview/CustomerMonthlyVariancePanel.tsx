"use client"

import { useMemo, useState } from "react"
import {
  fmtCount,
  fmtUsdSigned,
  useOppCustomerVariance,
  type OppCustomerVariance,
  type OppFilters,
} from "@/lib/ops-portal-overview-api"
import { PanelCard, CustomerNameCell, ExpandButton, ExpandModal, MiniTh, useMiniSort } from "./PanelShared"

// Moved verbatim out of SidePanels.tsx (layout 2026-10-28) — one panel per file.

// ---------------------------------------------------------------------------
// §3 — Customer Monthly Variance
// ---------------------------------------------------------------------------

export function CustomerVariance({
  filters,
  onPickCustomer,
  basis = "budget",
}: {
  filters: OppFilters
  onPickCustomer?: (c: string) => void
  basis?: "budget" | "mom"
}) {
  // ⚠ Same wire fields, OPPOSITE sign convention (§69 — one metric, one named
  // definition). CORP: actual − budget, so positive = ahead of plan. DFW:
  // last month − this month, so positive = the customer is DOWN this month.
  // The reader cannot infer which from the numbers, so the panel says it.
  const isMom = basis === "mom"
  const subtitle = isMom ? "Last month − this month" : "Actual − budget"
  const { data, isLoading, error } = useOppCustomerVariance(filters)
  const raw = useMemo(() => data?.data ?? [], [data])
  const [expanded, setExpanded] = useState(false)
  // Bruno R5 (#14): sortable on every column. Default = profit variance asc
  // (most-negative first), matching the prior fixed order.
  const { rows, sortKey, sortDir, onSort } = useMiniSort<OppCustomerVariance, "name" | "vol" | "profit">(raw, {
    name: (r) => (r.customer_name || "").toUpperCase(),
    vol: (r) => r.volume_var,
    profit: (r) => r.profit_var,
  }, "profit", isMom ? "desc" : "asc")
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
            {/* Red = the bad direction, which FLIPS with the basis: under
                actual−budget that is negative, under last−this it is positive
                (the customer shrank). Colouring off a fixed sign would paint
                every declining DFW customer green. */}
            <td className={`px-2 py-1 text-right tabular-nums ${(isMom ? r.volume_var > 0 : r.volume_var < 0) ? "text-[#DC2626]" : "text-[#374151]"}`}>
              {fmtCount(r.volume_var)}
            </td>
            <td className={`px-2 py-1 text-right tabular-nums ${(isMom ? r.profit_var > 0 : r.profit_var < 0) ? "text-[#DC2626]" : "text-[#374151]"}`}>
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
      leadingAction={
        <span className="flex items-center gap-2">
          <span className="rounded-full border border-[#E5E7EB] bg-[#F9FAFB] px-2 py-0.5 text-[9px] uppercase tracking-wide text-[#6B7280]">
            {subtitle}
          </span>
          <ExpandButton label="Customer Monthly Variance" onClick={() => setExpanded(true)} />
        </span>
      }
    >
      <div className="[contain:paint] max-h-[260px] overflow-x-hidden overflow-y-auto">{renderTable()}</div>
      {expanded && (
        <ExpandModal title="Customer Monthly Variance" onClose={() => setExpanded(false)}>
          {renderTable()}
        </ExpandModal>
      )}
    </PanelCard>
  )
}
