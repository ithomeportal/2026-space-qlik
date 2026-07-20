"use client"

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-07-20) R1 — "Cover" view: every status='A' load, with the
// carrier and carrier phone needed to chase coverage. Superset of "Pending to
// Cover" (which is only the status='A' loads that have no carrier yet).
// Small set (~121 CORP rows) → simple table, no sort/filter/pager, matching the
// Pending to Cover view.
// ---------------------------------------------------------------------------

import { fmtUsd, type OppCoverRow } from "@/lib/ops-portal-overview-api"
import { fmtSchedTs } from "./schedTime"

const COVER_COLUMNS: { label: string; align: "left" | "right" }[] = [
  { label: "Order", align: "left" },
  { label: "Team", align: "left" },
  { label: "Customer", align: "left" },
  { label: "Carrier", align: "left" },
  { label: "Carrier Phone", align: "left" },
  { label: "Orig Sched Early", align: "left" },
  { label: "Orig Sched Late", align: "left" },
  { label: "Lane", align: "left" },
  { label: "Revenue", align: "right" },
  { label: "Profit", align: "right" },
]

// A blank carrier on this board is meaningful — the load is not covered yet —
// so it reads as an explicit "Not covered" rather than an empty cell.
function CarrierCell({ carrier }: { carrier: string }) {
  if (!carrier) return <span className="text-[#B45309]">Not covered</span>
  return <span className="text-[#374151]">{carrier}</span>
}

// Phone comes from the same movement row as the carrier name, so the two always
// agree. It is absent on roughly two thirds of open loads.
function PhoneCell({ phone }: { phone: string }) {
  if (!phone) return <span className="text-[#9CA3AF]">—</span>
  return (
    <a
      href={`tel:${phone.replace(/[^\d+]/g, "")}`}
      className="tabular-nums text-[#2563EB] hover:underline"
    >
      {phone}
    </a>
  )
}

export default function CoverTable({ rows }: { rows: OppCoverRow[] }) {
  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
        <tr className="border-b border-[#E5E7EB]">
          {COVER_COLUMNS.map((c) => (
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
            <td colSpan={COVER_COLUMNS.length} className="px-3 py-6 text-center text-[#9CA3AF]">
              No open loads
            </td>
          </tr>
        ) : (
          rows.map((r) => (
            <tr key={r.order_id} className="border-b border-[#F3F4F6] hover:bg-[#FAFBFC]">
              <td className="px-2 py-1.5 font-medium text-[#1B3A5C]">{r.order_id}</td>
              <td className="px-2 py-1.5 text-[#374151]">{r.team_id}</td>
              <td className="px-2 py-1.5 text-[#374151]">
                {r.customer_name || <span className="text-[#9CA3AF]">—</span>}
              </td>
              <td className="px-2 py-1.5"><CarrierCell carrier={r.carrier} /></td>
              <td className="px-2 py-1.5"><PhoneCell phone={r.carrier_phone} /></td>
              <td className="px-2 py-1.5 tabular-nums text-[#6B7280]">{fmtSchedTs(r.orig_sched_early)}</td>
              <td className="px-2 py-1.5 tabular-nums text-[#6B7280]">{fmtSchedTs(r.orig_sched_late)}</td>
              <td className="px-2 py-1.5 text-[#374151]">
                {r.lane || <span className="text-[#9CA3AF]">—</span>}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(r.revenue)}</td>
              <td
                className={`px-2 py-1.5 text-right tabular-nums ${
                  r.profit < 0 ? "font-medium text-[#DC2626]" : "text-[#374151]"
                }`}
              >
                {fmtUsd(r.profit)}
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  )
}
