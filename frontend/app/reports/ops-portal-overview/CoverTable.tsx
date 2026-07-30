"use client"

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-07-20) R1 — "Cover" view: every status='A' load, with the
// carrier and carrier phone needed to chase coverage.
// Bruno (PDF 2026-07-23) R1: the caller now passes only carrier-assigned loads
// (the "Not covered" rows live in Pending to Cover).
// Bruno (PDF 2026-07-23) R5: every column is now sortable (client-side — the
// board is a small, fully-fetched set so sorting can't mis-rank a page).
// Bruno (PDF 2026-07-30) R3: Orig Sched Early dropped · the old "Orig Sched
// Late" (= customer_windows.orig_orig_sched_late) relabelled "Orig Orig Late" ·
// a new "Orig Sched Late" (= orig_sched_arrive_late) added beside it · plus
// Carrier Cost and Margin%.
// ---------------------------------------------------------------------------

import { fmtPct, fmtUsd, type OppCoverRow } from "@/lib/ops-portal-overview-api"
import { SortableTh, useSortable, type SortDir } from "@/components/SortableTable"
import { fmtSchedTs } from "./schedTime"

const COVER_COLUMNS: {
  label: string
  key: keyof OppCoverRow
  align: "left" | "right"
}[] = [
  { label: "Order", key: "order_id", align: "left" },
  { label: "Team", key: "team_id", align: "left" },
  { label: "Customer", key: "customer_name", align: "left" },
  { label: "Carrier", key: "carrier", align: "left" },
  { label: "Carrier Phone", key: "carrier_phone", align: "left" },
  // The wire field keeps its old name; only the header moved (§34).
  { label: "Orig Orig Late", key: "orig_sched_late", align: "left" },
  { label: "Orig Sched Late", key: "orig_sched_arrive_late", align: "left" },
  { label: "Lane", key: "lane", align: "left" },
  // Revenue − Carrier Cost = Profit, so the money block reads left to right.
  { label: "Revenue", key: "revenue", align: "right" },
  { label: "Carrier Cost", key: "carrier_cost", align: "right" },
  { label: "Profit", key: "profit", align: "right" },
  { label: "Margin%", key: "margin_pct", align: "right" },
]

// Money columns lead with desc (biggest first); text / schedule columns asc.
const MONEY_KEYS = new Set<keyof OppCoverRow>([
  "revenue", "carrier_cost", "profit", "margin_pct",
])
function coverDirForKey(key: string): SortDir {
  return MONEY_KEYS.has(key as keyof OppCoverRow) ? "desc" : "asc"
}

// A blank carrier is meaningful (not covered yet); kept defensive even though
// the Cover board now only receives carrier-assigned rows.
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
  // Default: soonest deadline first (matches the backend ORDER BY). Bruno R3
  // moved both onto orig_sched_arrive_late — it is populated on 94.6% of open
  // loads vs 65% for orig_sched_late, which parked a third of the board in a
  // NULLS-LAST block.
  const { sorted, ...sortState } = useSortable<OppCoverRow>(
    rows,
    "orig_sched_arrive_late",
    "asc",
    coverDirForKey,
  )
  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
        <tr className="border-b border-[#E5E7EB]">
          {COVER_COLUMNS.map((c) => (
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
            <td colSpan={COVER_COLUMNS.length} className="px-3 py-6 text-center text-[#9CA3AF]">
              No open loads
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
              <td className="px-2 py-1.5"><CarrierCell carrier={r.carrier} /></td>
              <td className="px-2 py-1.5"><PhoneCell phone={r.carrier_phone} /></td>
              <td className="px-2 py-1.5 tabular-nums text-[#6B7280]">{fmtSchedTs(r.orig_sched_late)}</td>
              <td className="px-2 py-1.5 tabular-nums text-[#6B7280]">{fmtSchedTs(r.orig_sched_arrive_late)}</td>
              <td className="px-2 py-1.5 text-[#374151]">
                {r.lane || <span className="text-[#9CA3AF]">—</span>}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(r.revenue)}</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-[#374151]">
                {fmtUsd(r.carrier_cost)}
              </td>
              <td
                className={`px-2 py-1.5 text-right tabular-nums ${
                  r.profit < 0 ? "font-medium text-[#DC2626]" : "text-[#374151]"
                }`}
              >
                {fmtUsd(r.profit)}
              </td>
              <td
                className={`px-2 py-1.5 text-right tabular-nums ${
                  r.margin_pct < 0 ? "font-medium text-[#DC2626]" : "text-[#374151]"
                }`}
              >
                {fmtPct(r.margin_pct)}
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  )
}
