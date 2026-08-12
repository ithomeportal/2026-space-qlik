"use client"

import { Loader2 } from "lucide-react"
import { SortableTh, useSortable } from "@/components/SortableTable"
import {
  useHdSpotTable,
  fmtDate,
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtVol,
  type HdSpotFilters,
  type HdSpotRow,
} from "@/lib/hd-spot-api"

type Fmt = "text" | "date" | "vol" | "count" | "usd" | "pct"

interface Col {
  key: keyof HdSpotRow
  label: string
  fmt: Fmt
  /** Start a new visual group (left divider) — Loads / Revenue / Carrier / Profit. */
  group?: boolean
  title?: string
}

/**
 * The single source of truth for the table shape.
 *
 * Everything downstream is DERIVED from this array — the header, each body row,
 * and critically the pinned Totals row's leading `colSpan`. A hand-typed
 * colSpan silently shifts every money figure one column left the moment a
 * column is added, putting real numbers under the wrong header with no error
 * (§61).
 */
const COLUMNS: Col[] = [
  { key: "equipment", label: "Equipment", fmt: "text" },
  { key: "date", label: "Date", fmt: "date" },

  { key: "offered", label: "Offered", fmt: "vol", group: true },
  { key: "quoted", label: "Quoted", fmt: "vol" },
  { key: "participation", label: "Participation", fmt: "pct" },
  { key: "awarded", label: "Awarded", fmt: "vol" },
  { key: "conversion", label: "Conversion", fmt: "pct" },

  {
    key: "loads",
    label: "Loads",
    fmt: "count",
    group: true,
    title:
      "All matched McLeod loads, with no contract-type filter. The three splits beside it count SPOT loads only, so Loads does not equal Cancelled + Covered + Pending — the CONTRACT-typed loads live in this column alone.",
  },
  { key: "loads_cancelled", label: "Loads Cancelled", fmt: "count" },
  { key: "loads_covered", label: "Loads Covered", fmt: "count" },
  { key: "loads_pending", label: "Loads Pending to Cover", fmt: "count" },

  { key: "revenue", label: "Revenue", fmt: "usd", group: true },
  { key: "revenue_cancelled", label: "Revenue Cancelled", fmt: "usd" },
  { key: "revenue_covered", label: "Revenue Covered", fmt: "usd" },
  { key: "revenue_pending", label: "Revenue Pending to Cover", fmt: "usd" },

  { key: "carrier_cost", label: "Carrier Cost", fmt: "usd", group: true },
  {
    key: "carrier_cost_cancelled",
    label: "Carrier Cost Cancelled",
    fmt: "usd",
    title:
      "Legitimately $0 or near-$0: a cancelled load keeps its revenue but sheds its carrier pay.",
  },
  { key: "carrier_cost_covered", label: "Carrier Cost Covered", fmt: "usd" },
  { key: "carrier_cost_pending", label: "Carrier Cost Pending to Cover", fmt: "usd" },

  { key: "profit", label: "Profit", fmt: "usd", group: true },
  {
    key: "profit_cancelled",
    label: "Profit Cancelled",
    fmt: "usd",
    title:
      "Often equal to Revenue Cancelled to the dollar — cancelled loads shed carrier pay, so their margin is ~100%.",
  },
  { key: "profit_covered", label: "Profit Covered", fmt: "usd" },
  { key: "profit_pending", label: "Profit Pending to Cover", fmt: "usd" },

  { key: "margin_covered", label: "Margin Covered", fmt: "pct", group: true },
  {
    key: "margin_pending",
    label: "Margin Pending to Cover",
    fmt: "pct",
    title:
      "Runs very high because the carrier has not been paid yet. It settles as the loads are covered.",
  },
]

/** Columns rendered before the first numeric one — this is what the Totals row
 *  must span. Derived, never typed. */
const LABEL_SPAN = COLUMNS.findIndex((c) => c.fmt !== "text" && c.fmt !== "date")

function render(c: Col, row: HdSpotRow) {
  const v = row[c.key] as number | string | null
  switch (c.fmt) {
    case "text":
      return String(v ?? "—")
    case "date":
      return fmtDate(v as string)
    case "vol":
      return fmtVol(v as number)
    case "count":
      return fmtCount(v as number)
    case "usd":
      return fmtUsd(v as number)
    case "pct":
      return fmtPct(v as number)
  }
}

const TH =
  "whitespace-nowrap px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide"
const TD = "whitespace-nowrap px-2 py-1 text-right tabular-nums"

export function DataTable({ filters }: { filters: HdSpotFilters }) {
  const { data, isLoading, error } = useHdSpotTable(filters)
  const rows = data?.data?.rows ?? []
  const totals = data?.data?.totals
  const sort = useSortable(rows)

  if (error) {
    return (
      <div className="rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-xs text-[#991B1B]">
        Could not load the table: {error instanceof Error ? error.message : "unknown error"}
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-baseline justify-between border-b border-[#E5E7EB] px-4 py-2">
        <h2 className="text-sm font-semibold text-[#1B3A5C]">Detail</h2>
        <span className="text-[10px] text-[#9CA3AF]">
          one row per equipment &amp; day · {rows.length.toLocaleString("en-US")} rows
        </span>
      </div>

      {isLoading && rows.length === 0 ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : rows.length === 0 ? (
        <div className="flex h-40 items-center justify-center text-xs text-[#6B7280]">
          No spot activity in this window.
        </div>
      ) : (
        // Wide table scrolls inside its own container — the page never scrolls
        // horizontally.
        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-0 text-xs">
            <thead className="sticky top-0 z-10 bg-[#F3F4F6] text-[#374151]">
              <tr>
                {COLUMNS.map((c, i) => (
                  <SortableTh
                    key={c.key}
                    label={c.title ? `${c.label} *` : c.label}
                    columnKey={c.key}
                    state={sort}
                    align={i < LABEL_SPAN ? "left" : "right"}
                    className={`${TH} ${
                      c.group ? "border-l border-[#D1D5DB]" : ""
                    }`}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {sort.sorted.map((r, idx) => (
                <tr
                  key={`${r.equipment}-${r.date}`}
                  className={idx % 2 ? "bg-[#FAFAFA]" : "bg-white"}
                >
                  {COLUMNS.map((c, i) => (
                    <td
                      key={c.key}
                      title={c.title}
                      className={`${
                        i < LABEL_SPAN
                          ? "whitespace-nowrap px-2 py-1 text-left font-medium text-[#111827]"
                          : TD
                      } ${c.group ? "border-l border-[#E5E7EB]" : ""}`}
                    >
                      {render(c, r)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
            {totals && (
              <tfoot className="sticky bottom-0">
                <tr className="bg-[#EEF2FF] font-semibold text-[#1B3A5C]">
                  {/* colSpan DERIVED from COLUMNS — see the note on LABEL_SPAN. */}
                  <td
                    colSpan={LABEL_SPAN}
                    className="whitespace-nowrap px-2 py-1.5 text-left"
                  >
                    Totals
                  </td>
                  {COLUMNS.slice(LABEL_SPAN).map((c) => (
                    <td
                      key={c.key}
                      className={`${TD} font-semibold ${
                        c.group ? "border-l border-[#D1D5DB]" : ""
                      }`}
                    >
                      {render(c, totals)}
                    </td>
                  ))}
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}

      <div className="space-y-1 border-t border-[#E5E7EB] px-4 py-2 text-[10px] leading-relaxed text-[#6B7280]">
        <p>
          * Hover a starred column for its caveat. Totals are a server-side
          aggregate over the whole filtered window, not a sum of the rows on
          screen.
        </p>
        <p>
          <strong>Loads</strong> has no contract-type filter while Cancelled /
          Covered / Pending count SPOT loads only, so the three do not add up to
          Loads. Load counts also skip zero-charge loads, which the money columns
          include — both quirks are carried over from the daily HD email so the
          two reports agree.
        </p>
      </div>
    </div>
  )
}
