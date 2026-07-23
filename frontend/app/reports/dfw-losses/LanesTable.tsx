"use client"

import { Loader2 } from "lucide-react"
import { useDfwLossesLanes, type DfwLossesFilters } from "@/lib/dfw-losses-api"
import { SortableTh, useSortable } from "@/components/SortableTable"
import { DfwLossesErrorBanner } from "./ErrorBanner"
import { fmtUsd, fmtCount } from "./format"

/** Server-side top-N: the backend returns the worst lanes by loss, LIMIT 50. */
const LANE_LIMIT = 50

export function LanesTable({ filters }: { filters: DfwLossesFilters }) {
  const { data, isLoading, isFetching, error } = useDfwLossesLanes(filters, LANE_LIMIT)
  const rows = data?.data ?? []

  // Rows are flat scalars, so the shared §38 primitive applies directly.
  // Default matches the server order: most-negative loss first. `loss` is
  // always <= 0, so its first click must be "asc" (worst first) — plain "desc"
  // would surface the least-bad lanes, the opposite of what the column means.
  const sort = useSortable(rows, "loss", "asc", (k) => (k === "loss" ? "asc" : "desc"))

  return (
    <section className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-[#E5E7EB] px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-[#1B3A5C]">Biggest Offender Lane</h2>
          {rows.length >= LANE_LIMIT && (
            <span
              className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[10px] text-[#92400E]"
              title={`Sorting reorders these ${LANE_LIMIT} lanes only — they are the worst ${LANE_LIMIT} by loss across the whole window.`}
            >
              Top {LANE_LIMIT} by loss
            </span>
          )}
        </div>
        {isFetching && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
      </div>

      <div className="px-4 pt-3">
        <DfwLossesErrorBanner errors={[error]} label="Lanes" />
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
        </div>
      ) : rows.length === 0 ? (
        <div className="px-4 py-12 text-center text-sm text-[#6B7280]">
          No loss-making lanes in the selected window.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-[#E5E7EB] bg-[#F9FAFB] text-left text-[#6B7280]">
                <SortableTh label="Customer" columnKey="customer" state={sort} />
                <SortableTh label="Origin" columnKey="origin" state={sort} />
                <SortableTh label="Destination" columnKey="destination" state={sort} />
                <SortableTh label="Loads" columnKey="loads" state={sort} align="right" />
                <SortableTh label="Loss" columnKey="loss" state={sort} align="right" />
              </tr>
            </thead>
            <tbody>
              {sort.sorted.map((r, i) => (
                <tr
                  key={`${r.customer}|${r.origin}|${r.destination}|${i}`}
                  className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]"
                >
                  <td
                    className="max-w-[220px] truncate px-3 py-1.5 text-[#111827]"
                    title={r.customer ?? undefined}
                  >
                    {r.customer ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 text-[#111827]">{r.origin ?? "—"}</td>
                  <td className="px-3 py-1.5 text-[#111827]">{r.destination ?? "—"}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#374151]">
                    {fmtCount(r.loads)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#DC2626]">
                    {fmtUsd(r.loss)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
