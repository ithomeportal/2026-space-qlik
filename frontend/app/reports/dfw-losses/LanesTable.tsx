"use client"

import { Loader2 } from "lucide-react"
import { useDfwLossesLanes, type DfwLossesFilters } from "@/lib/dfw-losses-api"
import { DfwLossesErrorBanner } from "./ErrorBanner"
import { fmtUsd, fmtCount } from "./format"

export function LanesTable({ filters }: { filters: DfwLossesFilters }) {
  const { data, isLoading, isFetching, error } = useDfwLossesLanes(filters)
  const rows = data?.data ?? []

  return (
    <section className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-[#E5E7EB] px-4 py-3">
        <h2 className="text-sm font-semibold text-[#1B3A5C]">Biggest Offender Lane</h2>
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
                <th className="px-3 py-2 font-semibold">Origin</th>
                <th className="px-3 py-2 font-semibold">Destination</th>
                <th className="px-3 py-2 text-right font-semibold">Loads</th>
                <th className="px-3 py-2 text-right font-semibold">Loss</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr
                  key={`${r.origin}|${r.destination}|${i}`}
                  className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]"
                >
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
