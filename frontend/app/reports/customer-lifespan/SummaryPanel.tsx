"use client"

import type { ReactNode } from "react"
import {
  fmtDate,
  fmtInt,
  fmtUsd,
  useBoard,
  type Assignment,
  type BoardTile,
  type Division,
  type ReportFilters,
  type Window,
} from "@/lib/customer-lifespan-api"
import { AssignedCell, ErrorBox, Loading, StatusChip } from "./ui"

/** Whether a rise is good news: fewer at-risk or lost customers is green. */
function Delta({ tile, riseIsGood }: { tile: BoardTile; riseIsGood: boolean }) {
  if (tile.delta_pct === null) {
    return <div className="text-[11px] text-[#9CA3AF]">{tile.prior === null ? "no earlier period to compare" : "none in the same period last year"}</div>
  }
  const up = tile.delta_pct > 0
  const flat = tile.delta_pct === 0
  const good = up === riseIsGood
  const tone = flat ? "text-[#6B7280]" : good ? "text-[#059669]" : "text-[#DC2626]"
  return (
    <div className="text-[11px] text-[#374151]">
      <span className={`font-semibold ${tone}`}>
        {flat ? "" : up ? "▲ +" : "▼ "}{Math.round(tile.delta_pct)}%
      </span>{" "}
      vs. same period last year
    </div>
  )
}

function Tile({ label, tile, riseIsGood, sub }: { label: string; tile: BoardTile; riseIsGood: boolean; sub: string }) {
  return (
    <div className="rounded-lg border-2 border-[#1B3A5C] bg-white px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-[#111827]">{label}</div>
      <div className="text-xl font-semibold tabular-nums text-[#1B3A5C]">{fmtInt(tile.value)}</div>
      <Delta tile={tile} riseIsGood={riseIsGood} />
      <div className="text-[11px] text-[#374151]">{sub}</div>
    </div>
  )
}

interface Column<T> {
  label: string
  cell: (row: T) => ReactNode
  left?: boolean
}

type Keyed = { customer_id: string; name: string }

const customer = <T extends Keyed>(): Column<T> => ({
  label: "Customer",
  left: true,
  cell: (r) => <span className="block max-w-[170px] truncate font-medium text-[#111827]" title={r.name}>{r.name}</span>,
})

const assigned = <T extends Assignment>(): Column<T> => ({
  label: "Team / Sales Exec.",
  left: true,
  cell: (r) => <AssignedCell row={r} />,
})

function BoardTable<T extends Keyed>({ title, note, rows, columns, onOpen, tall }: {
  tall?: boolean
  title: ReactNode
  note?: string
  rows: T[]
  columns: Column<T>[]
  onOpen: (id: string) => void
}) {
  return (
    <section className={`flex min-h-0 flex-col rounded-lg border-2 border-[#1B3A5C] bg-white p-3 ${tall ? "xl:row-span-2" : ""}`}>
      <h3 className="text-sm font-semibold text-[#1B3A5C]">
        {title} <span className="text-xs font-normal text-[#6B7280]">({fmtInt(rows.length)})</span>
      </h3>
      {note && <p className="text-[11px] text-[#6B7280]">{note}</p>}
      <div className={`mt-2 overflow-auto ${tall ? "max-h-[38rem]" : "max-h-72"}`}>
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-[#1B5E82] text-white">
            <tr>
              {columns.map((c) => (
                <th key={c.label} className={`px-2 py-1.5 align-bottom font-semibold ${c.left ? "text-left" : "text-right"}`}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.customer_id} onClick={() => onOpen(r.customer_id)} className="cursor-pointer border-t border-[#F3F4F6] hover:bg-[#F9FAFB]">
                {columns.map((c) => (
                  <td key={c.label} className={`whitespace-nowrap px-2 py-1 tabular-nums ${c.left ? "text-left" : "text-right"}`}>{c.cell(r)}</td>
                ))}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={columns.length} className="px-2 py-4 text-center text-[#6B7280]">None in these dates.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function SummaryPanel({ division, window, filters, onOpen }: {
  division: Division
  window: Window
  filters: ReportFilters
  onOpen: (id: string) => void
}) {
  const { data, error, isLoading } = useBoard(division, window, filters)
  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) return <Loading />
  const b = data.data
  const days = (r: { days_since_last: number }) => fmtInt(r.days_since_last)
  const age = (r: { age_months: number }) => `${fmtInt(r.age_months)} mo`
  const signed = (v: number, suffix = "") => `${v > 0 ? "+" : ""}${v}${suffix}`
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium text-[#1B3A5C]">Customer Retention | Summary</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Tile label="Active customers" tile={b.tiles.active} riseIsGood sub="Shipped in past 30 days" />
        <Tile label="At risk customers" tile={b.tiles.at_risk} riseIsGood={false} sub={`Last load 31–${window} days ago`} />
        <Tile label="First-year customers" tile={b.tiles.first_year} riseIsGood sub="First load in past 12 months" />
        <Tile label="Lost customers" tile={b.tiles.lost} riseIsGood={false} sub={`No loads for over ${window} days`} />
        <Tile label="Recovered" tile={b.tiles.recovered} riseIsGood sub="Reactivated customers" />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <BoardTable
          title="At Risk customers"
          rows={b.at_risk}
          onOpen={onOpen}
          columns={[customer(), assigned(),
            { label: "Age", cell: age },
            { label: "Days since last load", cell: days },
            { label: "Profit last 90 days", cell: (r) => fmtUsd(r.profit_90d) }]}
        />
        <BoardTable
          tall
          title="Customers with declining load volume"
          note="Loads in the last 30 days under the customer's monthly average of the 12 months before them. Customers under 2 loads a month are left out."
          rows={b.declining}
          onOpen={onOpen}
          columns={[customer(), assigned(),
            { label: "Avg. loads / mo", cell: (r) => r.avg_monthly_loads.toFixed(1) },
            { label: "Loads last 30 days", cell: (r) => fmtInt(r.loads_30d) },
            { label: "Change #", cell: (r) => signed(r.change) },
            { label: "Change %", cell: (r) => <span className="text-[#DC2626]">{signed(Math.round(r.change_pct), "%")}</span> }]}
        />
        <BoardTable
          title="First-year customers"
          rows={b.first_year}
          onOpen={onOpen}
          columns={[customer(), assigned(),
            { label: "Age", cell: age },
            { label: "Days since last load", cell: days },
            { label: "Status", left: true, cell: (r) => <StatusChip status={r.status} /> }]}
        />
        <BoardTable
          title={<><span className="text-[#DC2626]">LOST</span> customers</>}
          note={b.lost_since_returned > 0 ? `${fmtInt(b.lost_since_returned)} of them have since come back.` : undefined}
          rows={b.lost}
          onOpen={onOpen}
          columns={[customer(), assigned(),
            { label: "Days since last load", cell: days },
            { label: "Last load date", cell: (r) => fmtDate(r.last_ship) }]}
        />
        <BoardTable
          title={<><span className="text-[#059669]">RECOVERED</span> customers</>}
          rows={b.recovered}
          onOpen={onOpen}
          columns={[customer(), assigned(),
            { label: "Days since last load", cell: days },
            { label: "Status", left: true, cell: (r) => <StatusChip status={r.status} /> }]}
        />
      </div>
    </div>
  )
}
