"use client"

import type { HrDeptBar } from "@/lib/hr-access-api"

interface Props {
  rows: HrDeptBar[]
}

// Horizontal-ish stacked bar per department — green bar UP, red bar DOWN from a
// zero line. Mirrors Bruno's Qlik bar chart on page 5 of the PDF.
// Rendered as plain CSS (no SVG) so text handling is natural.

const GREEN = "#16A34A"
const RED = "#DC2626"

export function HrDeptBarChart({ rows }: Props) {
  if (rows.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[#E5E7EB] bg-white text-xs text-[#6B7280]">
        No events in the selected window.
      </div>
    )
  }

  const maxBar = Math.max(1, ...rows.map((r) => Math.max(r.on_time, r.out_of_time)))

  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white p-3">
      <div className="mb-2 flex items-center gap-4 text-[10px] text-[#374151]">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-3 rounded-sm" style={{ background: GREEN }} />
          On Time
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-3 rounded-sm" style={{ background: RED }} />
          Out of Time
        </span>
        <span className="ml-auto text-[#9CA3AF]">Ignores department filter</span>
      </div>

      <div className="grid grid-flow-col auto-cols-fr gap-2 overflow-x-auto pb-2">
        {rows.map((r) => {
          const gh = (r.on_time / maxBar) * 100
          const rh = (r.out_of_time / maxBar) * 100
          return (
            <div key={r.department} className="flex min-w-[60px] flex-col items-center gap-1">
              {/* Green (On Time) bar above baseline */}
              <div className="flex h-[80px] w-full flex-col items-center justify-end">
                <span className="mb-0.5 text-[10px] font-semibold text-[#047857]">
                  {r.on_time || ""}
                </span>
                <div
                  className="w-full rounded-sm"
                  style={{ height: `${gh}%`, background: GREEN, minHeight: r.on_time ? 2 : 0 }}
                />
              </div>
              {/* Red (Out of Time) bar below baseline */}
              <div className="flex h-[80px] w-full flex-col items-start justify-start">
                <div
                  className="w-full rounded-sm"
                  style={{ height: `${rh}%`, background: RED, minHeight: r.out_of_time ? 2 : 0 }}
                />
                <span className="mt-0.5 text-[10px] font-semibold text-[#B91C1C]">
                  {r.out_of_time || ""}
                </span>
              </div>
              <div
                className="w-full truncate text-center text-[10px] text-[#374151]"
                title={r.department}
              >
                {r.department}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
