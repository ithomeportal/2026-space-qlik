"use client"

import { useMemo } from "react"
import {
  fmtCount,
  fmtUsd,
  useOppCustomerOverPay,
  type OppCustomerOverPayRow,
  type OppCustomerOverPayTotals,
  type OppFilters,
} from "@/lib/ops-portal-overview-api"
import { PanelCard, CustomerNameCell, MiniTh, useMiniSort } from "./PanelShared"

// Moved verbatim out of SidePanels.tsx (layout 2026-10-28) — one panel per file.

// ---------------------------------------------------------------------------
// §4b — Over Pay (Bruno "Ops Portal Updates" 2026-10-16 R4; replaced the R14
// "Not Billed" table). eSavings-from-Carriers over pay, recomputed server-side
// for this page's scope/filters/window. Rows = customers with Over Pay < 0;
// the Total row is the server's whole-scope total (§44): its Loads counts
// EVERY qualifying load in scope, incl. customers with no over pay (they add
// $0 to Over Pay), so both totals span one population (§96).
// ---------------------------------------------------------------------------

export function CustomerOverPay({ filters, onPickCustomer }: { filters: OppFilters; onPickCustomer?: (c: string) => void }) {
  const q = useOppCustomerOverPay(filters)
  const totals = q.data?.meta?.totals as OppCustomerOverPayTotals | undefined
  const raw = useMemo(() => q.data?.data ?? [], [q.data])
  // Default = over pay asc (most negative first), the server's order.
  const { rows: sorted, sortKey, sortDir, onSort } = useMiniSort<OppCustomerOverPayRow, "name" | "loads" | "overpay">(raw, {
    name: (r) => (r.customer_name || "").toUpperCase(),
    loads: (r) => r.loads,
    overpay: (r) => r.over_pay,
  }, "overpay", "asc")
  return (
    <PanelCard
      title="Over Pay"
      icon=""
      loading={q.isLoading}
      error={q.error}
      action={
        <span
          className="rounded-full border border-[#E5E7EB] bg-white px-2 py-0.5 text-[9px] font-normal uppercase tracking-wide text-[#6B7280]"
          title="Carrier pay above the eSavings quarterly lane base, per lane-month — same rules as eSavings from Carriers. Loads with carrier pay under $201 are excluded."
        >
          vs eSavings quarterly lane base (loads ≥ $201)
        </span>
      }
    >
      <div className="[contain:paint] max-h-[180px] overflow-x-hidden overflow-y-auto">
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
              <MiniTh k="overpay" align="right" sortKey={sortKey} dir={sortDir} onSort={onSort}>Over Pay</MiniTh>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr><td colSpan={3} className="px-2 py-3 text-center text-[#9CA3AF]">No over pay</td></tr>
            ) : sorted.map((r) => (
              <tr key={r.customer_name} className="border-t border-[#F3F4F6]">
                <td className="truncate px-2 py-1 text-[#374151]" title={r.customer_name}>
                  <CustomerNameCell name={r.customer_name} onPick={onPickCustomer} />
                </td>
                <td className="px-2 py-1 text-right tabular-nums text-[#374151]">{fmtCount(r.loads)}</td>
                <td className="px-2 py-1 text-right tabular-nums text-[#DC2626]">{fmtUsd(r.over_pay)}</td>
              </tr>
            ))}
          </tbody>
          {totals && (
            <tfoot className="sticky bottom-0 bg-[#F9FAFB]">
              <tr
                className="border-t border-[#E5E7EB] font-semibold text-[#1B3A5C]"
                title={`All qualifying loads in scope, incl. customers with no over pay. ${fmtCount(totals.customers)} customer(s) with over pay carry ${fmtCount(totals.listed_loads)} of them.`}
              >
                <td className="px-2 py-1">Total (all in scope)</td>
                <td className="px-2 py-1 text-right tabular-nums">{fmtCount(totals.loads)}</td>
                <td className="px-2 py-1 text-right tabular-nums text-[#DC2626]">{fmtUsd(totals.over_pay)}</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </PanelCard>
  )
}
