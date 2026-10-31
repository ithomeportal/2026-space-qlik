"use client"

import { useMemo, useState } from "react"
import {
  fmtCount,
  fmtUsdSigned,
  useOppCustomerLosses,
  type OppCustomerLoss,
  type OppFilters,
} from "@/lib/ops-portal-overview-api"
import { PanelCard, CustomerNameCell, ExpandButton, ExpandModal, MiniTh, useMiniSort } from "./PanelShared"

// Moved verbatim out of SidePanels.tsx (layout 2026-10-28) — one panel per file.

// ---------------------------------------------------------------------------
// §4 — Customer Monthly Losses
// ---------------------------------------------------------------------------

export function CustomerLosses({ filters, onPickCustomer }: { filters: OppFilters; onPickCustomer?: (c: string) => void }) {
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
      <div className="[contain:paint] max-h-[180px] overflow-x-hidden overflow-y-auto">{renderTable()}</div>
      {expanded && (
        <ExpandModal title="Customer Monthly Losses" onClose={() => setExpanded(false)}>
          {renderTable()}
        </ExpandModal>
      )}
    </PanelCard>
  )
}
