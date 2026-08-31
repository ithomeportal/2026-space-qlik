"use client"

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-07-15) R16 — "Pending to Cover" view: status='A' loads with
// no carrier assigned. Small set → simple table.
// Extracted from ByOrder.tsx (Bruno PDF 2026-07-20) to keep that file in range.
// Bruno (PDF 2026-07-23) R5: every column is now sortable (client-side — the
// board is a small, fully-fetched set so sorting can't mis-rank a page).
// ---------------------------------------------------------------------------

import { fmtUsd, type OppPendingRow } from "@/lib/ops-portal-overview-api"
import { SortableTh, useSortable, type SortDir } from "@/components/SortableTable"
import { fmtSchedTs, fmtTimeToCover, timeToCoverColor } from "./schedTime"

const PENDING_COLUMNS: {
  label: string
  key: keyof OppPendingRow
  align: "left" | "right"
}[] = [
  { label: "Order", key: "order_id", align: "left" },
  { label: "Team", key: "team_id", align: "left" },
  // Bruno (PDF 2026-07-30) R2: Customer, between Team and Orig Sched Early.
  { label: "Customer", key: "customer_name", align: "left" },
  // Bruno (PDF 2026-08-31) R8: "Orig …" → "PU …". Labels only; wire keys stay.
  { label: "PU Sched Early", key: "orig_sched_early", align: "left" },
  { label: "PU Sched Late", key: "orig_sched_late", align: "left" },
  { label: "Lane", key: "lane", align: "left" },
  { label: "Revenue", key: "revenue", align: "right" },
  { label: "Time to Cover", key: "time_to_cover_hours", align: "right" },
]

// Revenue leads with desc (biggest first); Time to Cover asc = most urgent
// first; text / schedule columns asc.
function pendingDirForKey(key: string): SortDir {
  return key === "revenue" ? "desc" : "asc"
}

export default function PendingTable({ rows }: { rows: OppPendingRow[] }) {
  // Default: soonest pickup deadline first (matches the backend ORDER BY).
  const { sorted, ...sortState } = useSortable<OppPendingRow>(
    rows,
    "orig_sched_late",
    "asc",
    pendingDirForKey,
  )
  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
        <tr className="border-b border-[#E5E7EB]">
          {PENDING_COLUMNS.map((c) => (
            <SortableTh
              key={c.key}
              label={c.label}
              columnKey={c.key}
              state={sortState}
              align={c.align}
            />
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.length === 0 ? (
          <tr>
            <td colSpan={PENDING_COLUMNS.length} className="px-3 py-6 text-center text-[#9CA3AF]">
              No loads pending a carrier
            </td>
          </tr>
        ) : (
          sorted.map((r) => (
            <tr key={r.order_id} className="border-b border-[#F3F4F6] hover:bg-[#FAFBFC]">
              <td className="px-2 py-1.5 font-medium text-[#1B3A5C]">{r.order_id}</td>
              <td className="px-2 py-1.5 text-[#374151]">{r.team_id}</td>
              <td className="px-2 py-1.5 text-[#374151]">
                {r.customer_name || <span className="text-[#9CA3AF]">—</span>}
              </td>
              <td className="px-2 py-1.5 tabular-nums text-[#6B7280]">{fmtSchedTs(r.orig_sched_early)}</td>
              <td className="px-2 py-1.5 tabular-nums text-[#6B7280]">{fmtSchedTs(r.orig_sched_late)}</td>
              <td className="px-2 py-1.5 text-[#374151]">{r.lane || <span className="text-[#9CA3AF]">—</span>}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(r.revenue)}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {r.time_to_cover_hours == null ? (
                  <span className="text-[#9CA3AF]">—</span>
                ) : (
                  <span className={timeToCoverColor(r.time_to_cover_hours)}>
                    {fmtTimeToCover(r.time_to_cover_hours)}
                  </span>
                )}
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  )
}
