"use client"

import { useEffect } from "react"
import { Loader2, X } from "lucide-react"

// Bruno (PDF 2026-07-13): generic metric × column matrix modal, reused by the
// Week / Team break-outs of Team Budget Variance and Team Monthly Projection.
// Rows are the panel's metric set; columns are weeks or teams; each cell is
// pre-formatted (text + optional colour class) by the caller.

export interface MatrixCell {
  text: string
  className?: string
  // Bruno (PDF 2026-07-15) R3/R4: optional "% of total" shown small + light-gray
  // beside the value (instead of concatenated into the same text at full size).
  conc?: number | null
}

export interface MatrixRow {
  label: string
  cells: MatrixCell[]
  highlight?: boolean
}

export function MetricMatrixModal({
  title,
  subtitle,
  icon,
  columns,
  rows,
  loading,
  error,
  onClose,
}: {
  title: string
  subtitle?: string
  icon?: string
  columns: string[]
  rows: MatrixRow[]
  loading?: boolean
  error?: unknown
  onClose: () => void
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#E5E7EB] bg-[#F0F9FF] px-4 py-3">
          <div className="flex items-center gap-2">
            {icon && <span aria-hidden>{icon}</span>}
            <div className="text-sm font-semibold text-[#1B3A5C]">{title}</div>
            {subtitle && <span className="text-xs text-[#6B7280]">· {subtitle}</span>}
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-[#6B7280] hover:bg-white hover:text-[#111827]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
            </div>
          ) : error ? (
            <div className="rounded-lg border border-[#FCA5A5] bg-[#FEE2E2] px-3 py-2 text-xs text-[#991B1B]">
              Query failed: {(error as Error).message}
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#E5E7EB] text-[#6B7280]">
                  <th className="px-2 py-2 text-left text-[10px] font-semibold uppercase tracking-wider">
                    Metric
                  </th>
                  {columns.map((c, i) => (
                    <th key={i} className="px-2 py-2 text-right font-semibold text-[#1B3A5C]">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.label}
                    className={`border-b border-[#F3F4F6] ${row.highlight ? "bg-[#F0F9FF]" : ""}`}
                  >
                    <td className={`px-2 py-1.5 ${row.highlight ? "font-semibold text-[#1B3A5C]" : "text-[#6B7280]"}`}>
                      {row.label}
                    </td>
                    {row.cells.map((c, i) => (
                      <td key={i} className="px-2 py-1.5 text-right tabular-nums">
                        <span className="inline-flex items-baseline justify-end gap-1">
                          <span
                            className={
                              c.className ?? (row.highlight ? "font-bold text-[#1B3A5C]" : "text-[#374151]")
                            }
                          >
                            {c.text}
                          </span>
                          {c.conc != null && (
                            <span className="text-[10px] text-[#9CA3AF]">{c.conc.toFixed(2)}%</span>
                          )}
                        </span>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
