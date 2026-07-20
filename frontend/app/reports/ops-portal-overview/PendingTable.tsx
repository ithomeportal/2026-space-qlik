"use client"

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-07-15) R16 — "Pending to Cover" view: status='A' loads with
// no carrier assigned. Small set → simple table, no sort/filter/pager.
// Extracted from ByOrder.tsx (Bruno PDF 2026-07-20) to keep that file in range.
// ---------------------------------------------------------------------------

import { fmtUsd, type OppPendingRow } from "@/lib/ops-portal-overview-api"
import { fmtSchedTs, fmtTimeToCover, timeToCoverColor } from "./schedTime"

const PENDING_COLUMNS: { label: string; align: "left" | "right" }[] = [
  { label: "Order", align: "left" },
  { label: "Team", align: "left" },
  { label: "Orig Sched Early", align: "left" },
  { label: "Orig Sched Late", align: "left" },
  { label: "Lane", align: "left" },
  { label: "Revenue", align: "right" },
  { label: "Time to Cover", align: "right" },
]

export default function PendingTable({ rows }: { rows: OppPendingRow[] }) {
  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
        <tr className="border-b border-[#E5E7EB]">
          {PENDING_COLUMNS.map((c) => (
            <th
              key={c.label}
              className={`px-2 py-2 ${c.align === "right" ? "text-right" : "text-left"}`}
            >
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={PENDING_COLUMNS.length} className="px-3 py-6 text-center text-[#9CA3AF]">
              No loads pending a carrier
            </td>
          </tr>
        ) : (
          rows.map((r) => (
            <tr key={r.order_id} className="border-b border-[#F3F4F6] hover:bg-[#FAFBFC]">
              <td className="px-2 py-1.5 font-medium text-[#1B3A5C]">{r.order_id}</td>
              <td className="px-2 py-1.5 text-[#374151]">{r.team_id}</td>
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
