"use client"

import { useMemo, type ReactNode } from "react"
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import { useSortable, type SortDir, type SortState } from "@/components/SortableTable"
import {
  fmtDate,
  fmtInt,
  fmtUsd,
  useBoard,
  type Assignment,
  type Board,
  type BoardTile,
  type Division,
  type ReportFilters,
  type Status,
  type Window,
} from "@/lib/customer-lifespan-api"
import { AssignedCell, ErrorBox, Loading, StatusChip, negativeClass } from "./ui"

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
  /** The row field this column sorts on: a real field, or the header does nothing. */
  key: Extract<keyof T, string>
  label: string
  cell: (row: T) => ReactNode
  left?: boolean
  /** Direction of the first click. Default: text A→Z, numbers biggest first. */
  firstDir?: SortDir
}

type Keyed = Assignment & { customer_id: string; name: string }
type AtRiskRow = Board["at_risk"][number]
type DecliningRow = Board["declining"][number]
type FirstYearRow = Board["first_year"][number]
type LostRow = Board["lost"][number]
type RecoveredRow = Board["recovered"][number]

const CUSTOMER_COLUMN: Column<Keyed> = {
  key: "name",
  label: "Customer",
  left: true,
  cell: (r) => <span className="block max-w-[170px] truncate font-medium text-[#111827]" title={r.name}>{r.name}</span>,
}

const ASSIGNED_COLUMN: Column<Keyed> = {
  key: "assigned_to",
  label: "Team / Sales Exec.",
  left: true,
  cell: (r) => <AssignedCell row={r} />,
}

const days = (r: { days_since_last: number }) => fmtInt(r.days_since_last)
const age = (r: { age_months: number }) => `${fmtInt(r.age_months)} mo`
const signed = (v: number, suffix = "") => `${v > 0 ? "+" : ""}${v}${suffix}`
const status = (r: { status: Status }) => <StatusChip status={r.status} />

function ChangePct({ value }: { value: number }) {
  const pct = Math.round(value)
  return <span className={negativeClass(pct)}>{signed(pct, "%")}</span>
}

const AT_RISK_COLUMNS: Column<AtRiskRow>[] = [
  CUSTOMER_COLUMN,
  ASSIGNED_COLUMN,
  { key: "age_months", label: "Age", cell: age },
  { key: "days_since_last", label: "Days since last load", cell: days },
  { key: "profit_90d", label: "Profit last 90 days", cell: (r) => <span className={negativeClass(r.profit_90d)}>{fmtUsd(r.profit_90d)}</span> },
]

// A drop's first click shows the worst one: on a negative column, "biggest first" is the least bad.
const DECLINING_COLUMNS: Column<DecliningRow>[] = [
  CUSTOMER_COLUMN,
  ASSIGNED_COLUMN,
  { key: "avg_monthly_loads", label: "Avg. loads / mo", cell: (r) => r.avg_monthly_loads.toFixed(1) },
  { key: "loads_30d", label: "Loads last 30 days", cell: (r) => fmtInt(r.loads_30d) },
  { key: "change", label: "Change #", firstDir: "asc", cell: (r) => <span className={negativeClass(r.change)}>{signed(r.change)}</span> },
  { key: "change_pct", label: "Change %", firstDir: "asc", cell: (r) => <ChangePct value={r.change_pct} /> },
]

const FIRST_YEAR_COLUMNS: Column<FirstYearRow>[] = [
  CUSTOMER_COLUMN,
  ASSIGNED_COLUMN,
  { key: "age_months", label: "Age", cell: age },
  { key: "days_since_last", label: "Days since last load", cell: days },
  { key: "status", label: "Status", left: true, cell: status },
]

const LOST_COLUMNS: Column<LostRow>[] = [
  CUSTOMER_COLUMN,
  ASSIGNED_COLUMN,
  { key: "days_since_last", label: "Days since last load", cell: days },
  { key: "last_ship", label: "Last load date", firstDir: "asc", cell: (r) => fmtDate(r.last_ship) },
]

const RECOVERED_COLUMNS: Column<RecoveredRow>[] = [
  CUSTOMER_COLUMN,
  ASSIGNED_COLUMN,
  { key: "days_since_last", label: "Days since last load", cell: days },
  { key: "status", label: "Status", left: true, cell: status },
]

/**
 * White on the dark header in every state: SortableTh's active colour is navy, unreadable here.
 * The arrow is INLINE so it can wrap under the label: a flex row adds its width to every
 * column's minimum and pushes Change % out of the half-width tables (measured at 1440 px).
 */
function SortHeader<T>({ column, sort }: { column: Column<T>; sort: SortState }) {
  const active = sort.sortKey === column.key
  const Icon = !active ? ArrowUpDown : sort.sortDir === "asc" ? ArrowUp : ArrowDown
  const ariaSort = !active ? "none" : sort.sortDir === "asc" ? "ascending" : "descending"
  return (
    <th aria-sort={ariaSort} className={`px-2 py-1.5 align-bottom font-semibold ${column.left ? "text-left" : "text-right"}`}>
      <button
        type="button"
        onClick={() => sort.toggleSort(column.key)}
        title={`Sort by ${column.label}`}
        className={`font-semibold hover:underline ${column.left ? "text-left" : "text-right"}`}
      >
        {column.label}
        <Icon aria-hidden className={`ml-0.5 inline h-3 w-3 align-[-2px] ${active ? "" : "opacity-50"}`} />
      </button>
    </th>
  )
}

function BoardTable<T extends Keyed>({ title, note, rows, columns, onOpen, tall, defaultSort }: {
  tall?: boolean
  title: ReactNode
  note?: string
  rows: T[]
  columns: Column<T>[]
  onOpen: (id: string) => void
  /** The order the API already sends, when it IS a column: otherwise that column's first click looks dead. */
  defaultSort?: { key: Extract<keyof T, string>; dir: SortDir }
}) {
  // "NO TEAM" renders as a dash, so it sorts with the blanks rather than among the N's.
  const sortable = useMemo(
    () => rows.map((r) => (r.assigned_to === "NO TEAM" ? { ...r, assigned_to: null } : r)),
    [rows],
  )
  const { sorted, ...sort } = useSortable(sortable, defaultSort?.key ?? null, defaultSort?.dir ?? "desc", (key) => {
    const c = columns.find((col) => col.key === key)
    return c ? c.firstDir ?? (c.left ? "asc" : "desc") : "desc"
  })
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
              {columns.map((c) => <SortHeader key={c.key} column={c} sort={sort} />)}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.customer_id} onClick={() => onOpen(r.customer_id)} className="cursor-pointer border-t border-[#F3F4F6] hover:bg-[#F9FAFB]">
                {columns.map((c) => (
                  <td key={c.key} className={`whitespace-nowrap px-2 py-1 tabular-nums ${c.left ? "text-left" : "text-right"}`}>{c.cell(r)}</td>
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
          columns={AT_RISK_COLUMNS}
          defaultSort={{ key: "profit_90d", dir: "desc" }}
        />
        <BoardTable
          tall
          title="Customers with declining load volume"
          note="Loads in the last 30 days under the customer's monthly average of the 12 months before them. Customers under 2 loads a month are left out."
          rows={b.declining}
          onOpen={onOpen}
          columns={DECLINING_COLUMNS}
          defaultSort={{ key: "change", dir: "asc" }}
        />
        <BoardTable
          title="First-year customers"
          rows={b.first_year}
          onOpen={onOpen}
          columns={FIRST_YEAR_COLUMNS}
        />
        <BoardTable
          title={<><span className="text-[#DC2626]">LOST</span> customers</>}
          note={b.lost_since_returned > 0 ? `${fmtInt(b.lost_since_returned)} of them have since come back.` : undefined}
          rows={b.lost}
          onOpen={onOpen}
          columns={LOST_COLUMNS}
        />
        <BoardTable
          title={<><span className="text-[#059669]">RECOVERED</span> customers</>}
          rows={b.recovered}
          onOpen={onOpen}
          columns={RECOVERED_COLUMNS}
        />
      </div>
    </div>
  )
}
