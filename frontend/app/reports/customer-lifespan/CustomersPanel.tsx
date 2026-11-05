"use client"

import { ArrowDown, ArrowUp } from "lucide-react"
import { useSortable } from "@/components/SortableTable"
import {
  STATUS_META,
  fmtDate,
  fmtInt,
  fmtMonths,
  fmtPct,
  fmtUsd,
  fmtUsdCompact,
  type CustomerRow,
} from "@/lib/customer-lifespan-api"
import { AssignedCell, Sparkline, StatusChip } from "./ui"

const COLUMNS: { k: keyof CustomerRow; label: string; align?: "left" }[] = [
  { k: "name", label: "Customer", align: "left" },
  { k: "status", label: "Status", align: "left" },
  { k: "assigned_to", label: "TEAM / Sales Exec.", align: "left" },
  { k: "first_ship", label: "First load" },
  { k: "last_ship", label: "Last load" },
  { k: "days_since_last", label: "Days since last load" },
  { k: "lifespan_months", label: "Customer lifespan" },
  { k: "active_months", label: "Months shipping" },
  { k: "reactivations", label: "Reactivations" },
  { k: "loads", label: "Total loads" },
  { k: "revenue", label: "Total Revenue ($)" },
  { k: "margin", label: "Profit ($)" },
  { k: "margin_pct", label: "Margin %" },
  { k: "avg_monthly_margin", label: "Avg. monthly Profit ($)" },
]

// Text and date columns read best A→Z / oldest first; numbers biggest first.
const ASC_FIRST = new Set<string>(["name", "status", "assigned_to", "first_ship", "last_ship"])

export function CustomersPanel({ rows, onOpen }: { rows: CustomerRow[]; onOpen: (id: string) => void }) {
  const { sorted, sortKey, sortDir, toggleSort } = useSortable(rows, "revenue", "desc", (k) =>
    ASC_FIRST.has(k) ? "asc" : "desc",
  )
  const td = "px-2 py-1.5 text-right tabular-nums"
  return (
    <div className="max-h-[70vh] overflow-auto rounded-lg border border-[#E5E7EB]">
      <table className="w-full text-xs">
        <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[#6B7280]">
          <tr>
            {COLUMNS.map((c) => (
              <th
                key={c.k}
                onClick={() => toggleSort(c.k)}
                className={`cursor-pointer select-none whitespace-nowrap px-2 py-2 font-medium hover:text-[#111827] ${
                  c.align === "left" ? "text-left" : "text-right"
                }`}
              >
                {c.label}
                {sortKey === c.k && (sortDir === "asc" ? <ArrowUp className="ml-0.5 inline h-3 w-3" /> : <ArrowDown className="ml-0.5 inline h-3 w-3" />)}
              </th>
            ))}
            <th className="px-2 py-2 text-left font-medium">Revenue · last 24 mo</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr
              key={r.customer_id}
              onClick={() => onOpen(r.customer_id)}
              className="cursor-pointer border-t border-[#F3F4F6] hover:bg-[#F9FAFB]"
            >
              <td className="max-w-[260px] px-2 py-1.5">
                <div className="truncate font-medium text-[#111827]" title={r.name}>{r.name}</div>
                <div className="text-[10px] text-[#9CA3AF]">{r.customer_id} · {r.divisions.join(" · ")}</div>
              </td>
              <td className="px-2 py-1.5"><StatusChip status={r.status} /></td>
              <td className="px-2 py-1.5"><AssignedCell row={r} /></td>
              <td className={td}>{fmtDate(r.first_ship)}</td>
              <td className={td}>{fmtDate(r.last_ship)}</td>
              <td className={td}>{fmtInt(r.days_since_last)}</td>
              <td className={td}>{fmtMonths(r.lifespan_months)}</td>
              <td className={td}>{fmtInt(r.active_months)}</td>
              <td className={td}>{r.reactivations > 0 ? `${r.reactivations}×` : "—"}</td>
              <td className={td}>{fmtInt(r.loads)}</td>
              <td className={td} title={fmtUsd(r.revenue)}>{fmtUsdCompact(r.revenue)}</td>
              <td className={`${td} ${r.margin < 0 ? "text-[#DC2626]" : ""}`} title={fmtUsd(r.margin)}>{fmtUsdCompact(r.margin)}</td>
              <td className={`${td} ${(r.margin_pct ?? 0) < 0 ? "text-[#DC2626]" : ""}`}>{fmtPct(r.margin_pct)}</td>
              <td className={td}>{fmtUsd(r.avg_monthly_margin)}</td>
              <td className="px-2 py-1.5"><Sparkline values={r.spark_24m} color={STATUS_META[r.status].color} /></td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr><td colSpan={COLUMNS.length + 1} className="px-2 py-6 text-center text-[#6B7280]">No customer matches these filters.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
