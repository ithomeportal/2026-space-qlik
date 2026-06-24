"use client"

import { useEffect, useMemo, useState } from "react"
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Clock,
  Loader2,
  Maximize2,
  X,
} from "lucide-react"
import {
  fmtDuration,
  fmtPct,
  fmtUsd,
  useOppByOrder,
  type OppFilters,
  type OppOrderRow,
  type OppOrderTotals,
} from "@/lib/ops-portal-overview-api"

interface Props {
  filters: OppFilters
  // R9: drill to a customer / lane when the host page wires these in.
  onPickCustomer?: (customer: string) => void
  onPickLane?: (lane: string) => void
}

// Bruno R4 (2026-05-27): load-level Production table. Server-side sort on every
// column (the set is load-level, so sorting only the fetched page would mis-rank).
// Bruno R5 (2026-06-01): + OTP %, OTD %, Transit Time (with a live timer for
// loads still in progress).
// R19 (2026-06-24): + Status column (between Lane and Revenue).
// R14/R13/R9 (2026-06-24): client-side column filters, client-side pagination,
// clickable Customer/Lane drill cells, and an expand-to-modal view.
type ColumnKey =
  | "order" | "team" | "departure" | "customer" | "lane" | "status"
  | "revenue" | "profit" | "margin" | "otp" | "otd" | "transit"

const COLUMNS: {
  k: ColumnKey
  label: string
  align: "left" | "right"
}[] = [
  { k: "order",     label: "Order",        align: "left" },
  { k: "team",      label: "Team",         align: "left" },
  { k: "departure", label: "Departure",    align: "left" },
  { k: "customer",  label: "Customer",     align: "left" },
  { k: "lane",      label: "Lane",         align: "left" },
  { k: "status",    label: "Status",       align: "left" },
  { k: "revenue",   label: "Revenue",      align: "right" },
  { k: "profit",    label: "Profit",       align: "right" },
  { k: "margin",    label: "Margin",       align: "right" },
  { k: "otp",       label: "OTP %",        align: "right" },
  { k: "otd",       label: "OTD %",        align: "right" },
  { k: "transit",   label: "Transit Time", align: "right" },
]

const NUMERIC_DESC_FIRST = new Set<ColumnKey>([
  "revenue", "profit", "margin", "otp", "otd", "transit",
])

const LIMIT = 500
const PAGE_SIZE = 50

// R14: client-side substring filters (case-insensitive) over fetched rows.
interface ColFilters {
  order: string
  team: string
  customer: string
  lane: string
}

const EMPTY_FILTERS: ColFilters = { order: "", team: "", customer: "", lane: "" }

function applyColFilters(rows: OppOrderRow[], f: ColFilters): OppOrderRow[] {
  const order = f.order.trim().toLowerCase()
  const team = f.team.trim().toLowerCase()
  const customer = f.customer.trim().toLowerCase()
  const lane = f.lane.trim().toLowerCase()
  if (!order && !team && !customer && !lane) return rows
  return rows.filter((r) => {
    if (order && !String(r.order_id).toLowerCase().includes(order)) return false
    if (team && !(r.team_id ?? "").toLowerCase().includes(team)) return false
    if (customer && !(r.customer_name ?? "").toLowerCase().includes(customer)) return false
    if (lane && !(r.lane ?? "").toLowerCase().includes(lane)) return false
    return true
  })
}

export function ByOrder({ filters, onPickCustomer, onPickLane }: Props) {
  const [sortKey, setSortKey] = useState<ColumnKey>("revenue")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
  // status sorts as text; never sent for server sort (column not server-sortable
  // by that grain), so fall back to revenue_desc for the wire if status is active.
  const wireKey: ColumnKey = sortKey === "status" ? "revenue" : sortKey
  const sort = `${wireKey}_${sortDir}`

  const [colFilters, setColFilters] = useState<ColFilters>(EMPTY_FILTERS)
  const [page, setPage] = useState(0)
  const [expanded, setExpanded] = useState(false)

  const { data, isLoading, error } = useOppByOrder(filters, { sort, limit: LIMIT })
  const rows: OppOrderRow[] = data?.data ?? []
  const totals = data?.meta?.totals as OppOrderTotals | undefined
  const returned = (data?.meta?.returned as number | undefined) ?? rows.length
  const total = totals?.n_orders ?? returned

  // R14: filtered set (client-side) feeds both render + pagination.
  const filtered = useMemo(() => applyColFilters(rows, colFilters), [rows, colFilters])

  // R13: client-side pagination over the filtered set.
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const pageRows = useMemo(
    () => filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE),
    [filtered, safePage],
  )

  // Reset to first page whenever the filtered universe shifts.
  useEffect(() => {
    setPage(0)
  }, [colFilters, sort])

  // Esc closes the expand modal.
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [expanded])

  // Bruno R5 #11: live in-transit timer — re-render every 30s while any load
  // is still in progress (otherwise the clock is idle).
  const hasInProgress = rows.some((r) => r.in_progress)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!hasInProgress) return
    const id = setInterval(() => setNow(Date.now()), 30000)
    return () => clearInterval(id)
  }, [hasInProgress])

  const onSort = (k: ColumnKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(k)
      // Numeric columns default desc, text columns asc.
      setSortDir(NUMERIC_DESC_FIRST.has(k) ? "desc" : "asc")
    }
  }

  const table = (
    <OrderTable
      rows={pageRows}
      totals={totals}
      total={total}
      sortKey={sortKey}
      sortDir={sortDir}
      onSort={onSort}
      colFilters={colFilters}
      onColFilter={(patch) => setColFilters((p) => ({ ...p, ...patch }))}
      now={now}
      onPickCustomer={onPickCustomer}
      onPickLane={onPickLane}
    />
  )

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          title="Expand"
          aria-label="Expand table"
          className="text-[#6B7280] hover:text-[#1B3A5C]"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
        <span className="rounded-md bg-[#1B3A5C] px-2 py-0.5 text-xs font-semibold uppercase text-white">
          By Order
        </span>
        <span className="text-[10px] uppercase tracking-wider text-[#6B7280]">
          Production data · load-level
        </span>
        <div className="ml-auto flex items-center gap-3 text-[10px] text-[#6B7280]">
          {isLoading && <Loader2 className="h-3 w-3 animate-spin" />}
          {total > returned ? (
            <span>Showing top {returned} of {total.toLocaleString()} · click a header to sort</span>
          ) : (
            <span>Click any column header to sort</span>
          )}
          <Pager
            page={safePage}
            pageCount={pageCount}
            onPrev={() => setPage((p) => Math.max(0, p - 1))}
            onNext={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
          />
        </div>
      </div>

      {error ? (
        <div className="px-3 py-4 text-sm text-[#DC2626]">Failed to load orders</div>
      ) : (
        <div className="max-h-[480px] overflow-auto">{table}</div>
      )}

      {expanded && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setExpanded(false)}
        >
          <div
            className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg bg-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
              <span className="rounded-md bg-[#1B3A5C] px-2 py-0.5 text-xs font-semibold uppercase text-white">
                By Order
              </span>
              <div className="ml-auto flex items-center gap-3 text-[10px] text-[#6B7280]">
                <Pager
                  page={safePage}
                  pageCount={pageCount}
                  onPrev={() => setPage((p) => Math.max(0, p - 1))}
                  onNext={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                />
                <button
                  type="button"
                  onClick={() => setExpanded(false)}
                  aria-label="Close"
                  className="text-[#6B7280] hover:text-[#1B3A5C]"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="overflow-auto">{table}</div>
          </div>
        </div>
      )}
    </section>
  )
}

function Pager({
  page,
  pageCount,
  onPrev,
  onNext,
}: {
  page: number
  pageCount: number
  onPrev: () => void
  onNext: () => void
}) {
  return (
    <span className="inline-flex items-center gap-1">
      <button
        type="button"
        onClick={onPrev}
        disabled={page <= 0}
        aria-label="Previous page"
        className="rounded p-0.5 hover:bg-[#E5E7EB] disabled:opacity-30 disabled:hover:bg-transparent"
      >
        <ChevronLeft className="h-3.5 w-3.5" />
      </button>
      <span className="tabular-nums">
        Page {page + 1} of {pageCount}
      </span>
      <button
        type="button"
        onClick={onNext}
        disabled={page >= pageCount - 1}
        aria-label="Next page"
        className="rounded p-0.5 hover:bg-[#E5E7EB] disabled:opacity-30 disabled:hover:bg-transparent"
      >
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
    </span>
  )
}

function OrderTable({
  rows,
  totals,
  total,
  sortKey,
  sortDir,
  onSort,
  colFilters,
  onColFilter,
  now,
  onPickCustomer,
  onPickLane,
}: {
  rows: OppOrderRow[]
  totals: OppOrderTotals | undefined
  total: number
  sortKey: ColumnKey
  sortDir: "asc" | "desc"
  onSort: (k: ColumnKey) => void
  colFilters: ColFilters
  onColFilter: (patch: Partial<ColFilters>) => void
  now: number
  onPickCustomer?: (customer: string) => void
  onPickLane?: (lane: string) => void
}) {
  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
        <tr className="border-b border-[#E5E7EB]">
          {COLUMNS.map((c) => (
            <SortableTh
              key={c.k}
              align={c.align}
              active={sortKey === c.k}
              dir={sortDir}
              onClick={() => onSort(c.k)}
            >
              {c.label}
            </SortableTh>
          ))}
        </tr>
        {/* R14: per-column substring filter row */}
        <tr className="border-b border-[#E5E7EB] bg-white">
          <FilterTd value={colFilters.order} onChange={(v) => onColFilter({ order: v })} placeholder="Order" />
          <FilterTd value={colFilters.team} onChange={(v) => onColFilter({ team: v })} placeholder="Team" />
          <td />
          <FilterTd value={colFilters.customer} onChange={(v) => onColFilter({ customer: v })} placeholder="Customer" />
          <FilterTd value={colFilters.lane} onChange={(v) => onColFilter({ lane: v })} placeholder="Lane" />
          <td colSpan={7} />
        </tr>
        {totals && (
          <tr className="border-b border-[#E5E7EB] bg-[#EFF6FF] font-semibold text-[#1B3A5C]">
            <td className="px-2 py-1.5" colSpan={6}>
              TOTAL · {total.toLocaleString()} orders
            </td>
            <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(totals.revenue)}</td>
            <td className={`px-2 py-1.5 text-right tabular-nums ${totals.profit < 0 ? "text-[#DC2626]" : ""}`}>
              {fmtUsd(totals.profit)}
            </td>
            <td className={`px-2 py-1.5 text-right tabular-nums ${totals.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
              {fmtPct(totals.margin_pct)}
            </td>
            <td className="px-2 py-1.5" colSpan={3} />
          </tr>
        )}
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-[#9CA3AF]">
              No orders in scope
            </td>
          </tr>
        ) : rows.map((r) => (
          <tr key={r.order_id} className="border-b border-[#F3F4F6] hover:bg-[#FAFBFC]">
            <td className="px-2 py-1.5 font-medium text-[#1B3A5C]">{r.order_id}</td>
            <td className="px-2 py-1.5 text-[#374151]">{r.team_id}</td>
            <td className="px-2 py-1.5 tabular-nums text-[#6B7280]">{r.departure}</td>
            <td className="px-2 py-1.5 text-[#374151]">
              {onPickCustomer && r.customer_name ? (
                <button
                  type="button"
                  onClick={() => onPickCustomer(r.customer_name)}
                  className="text-[#2563EB] hover:underline"
                >
                  {r.customer_name}
                </button>
              ) : (
                r.customer_name
              )}
            </td>
            <td className="px-2 py-1.5 text-[#374151]">
              {onPickLane && r.lane ? (
                <button
                  type="button"
                  onClick={() => onPickLane(r.lane)}
                  className="text-[#2563EB] hover:underline"
                >
                  {r.lane}
                </button>
              ) : (
                r.lane
              )}
            </td>
            <td className="px-2 py-1.5 uppercase text-[#6B7280]">{r.status}</td>
            <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(r.revenue)}</td>
            <td className={`px-2 py-1.5 text-right tabular-nums ${r.profit < 0 ? "text-[#DC2626]" : ""}`}>
              {fmtUsd(r.profit)}
            </td>
            <td className={`px-2 py-1.5 text-right tabular-nums ${r.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
              {fmtPct(r.margin_pct)}
            </td>
            <td className="px-2 py-1.5 text-right tabular-nums">{fmtPct(r.otp_pct)}</td>
            <td className="px-2 py-1.5 text-right tabular-nums">{fmtPct(r.otd_pct)}</td>
            <td className="px-2 py-1.5 text-right tabular-nums">
              <TransitCell row={r} now={now} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function FilterTd({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
}) {
  return (
    <td className="px-1.5 py-1">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded border border-[#E5E7EB] bg-white px-1.5 py-0.5 text-[10px] font-normal normal-case text-[#374151] placeholder:text-[#9CA3AF] focus:border-[#2563EB] focus:outline-none"
      />
    </td>
  )
}

// Bruno R5 #11: Transit Time cell. Completed loads show arrival − departure;
// loads still in progress tick a live clock (now − departure) in amber.
function TransitCell({ row, now }: { row: OppOrderRow; now: number }) {
  if (row.in_progress && row.departed_at) {
    // Timestamp is CST wall-clock without a tz; parse as local — good enough
    // for an elapsed-time indicator.
    const dep = new Date(row.departed_at.replace(" ", "T")).getTime()
    const elapsed = Number.isFinite(dep) ? (now - dep) / 1000 : 0
    return (
      <span className="inline-flex items-center gap-1 font-medium text-[#B45309]">
        <Clock className="h-3 w-3 animate-pulse" />
        {fmtDuration(elapsed)}
      </span>
    )
  }
  if (row.transit_seconds && row.transit_seconds > 0) {
    return <span className="text-[#374151]">{fmtDuration(row.transit_seconds)}</span>
  }
  return <span className="text-[#9CA3AF]">—</span>
}

function SortableTh({
  children,
  align = "left",
  active,
  dir,
  onClick,
}: {
  children: React.ReactNode
  align?: "left" | "right"
  active: boolean
  dir: "asc" | "desc"
  onClick: () => void
}) {
  const cls = align === "right" ? "text-right" : "text-left"
  const justify = align === "right" ? "justify-end" : "justify-start"
  return (
    <th className={`px-2 py-2 ${cls}`}>
      <button
        type="button"
        onClick={onClick}
        className={`inline-flex w-full items-center gap-1 ${justify} ${
          active ? "font-bold text-[#1B3A5C]" : "hover:text-[#374151]"
        }`}
      >
        {children}
        {active && (dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  )
}
