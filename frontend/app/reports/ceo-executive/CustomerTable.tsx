"use client"

import { useCallback, useMemo, useState } from "react"
import { ArrowDown, ArrowUp, ArrowUpDown, Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  type CeoCustomerRow,
  type CeoCustomerTotals,
} from "@/lib/ceo-api"
import { ExpandButton, ExpandModal } from "@/app/reports/ops-portal-overview/PanelShared"
import { marginCellClass } from "./margin-color"
import { CustomerLink } from "./customer-cell"
import {
  CUSTOMER_COLUMNS,
  ariaSortFor,
  describeCustomerSort,
  nextCustomerSort,
  sortCustomerRows,
  type CustomerSort,
  type CustomerSortKey,
} from "./customer-table-sort"

// "Profit by Customer" / "Worst Profit by Customer" (CEO Executive → Overview).
// Every column sorts client-side; the Totals row stays pinned above the rows.
// The expand button opens the same table in a modal with every row the server
// sent (the inline card already renders them all inside a scroll box; the
// server caps each list at LIMIT 200 — `count` is the full-universe figure).

type Tone = "green" | "red"

const HEAD_CLASS: Record<Tone, string> = {
  red: "bg-[#FEE2E2] text-[#991B1B]",
  green: "bg-[#D1FAE5] text-[#065F46]",
}

interface CustomerTableProps {
  title: string
  tone: Tone
  rows: CeoCustomerRow[]
  loading?: boolean
  /** The order the server sends and the table opens in. */
  defaultSort: CustomerSort
  /** Subtitle while `defaultSort` is active, e.g. "sorted by highest profit". */
  defaultHint: string
  /** Distinct-customer count for the header. Server-side over the full
   *  universe — never `rows.length`, which is LIMIT-200 capped (§44). */
  count?: number
  /** Show the count badge in the card header (the modal always notes a cap). */
  showCount?: boolean
  /** Pinned Totals row, server-side over the FULL universe (§44). Renders "—"
   *  if absent rather than a wrong number. */
  totals?: CeoCustomerTotals
  onCustomerSelect?: (customer: string) => void
}

export function CustomerTable({
  title,
  tone,
  rows,
  loading,
  defaultSort,
  defaultHint,
  count,
  showCount = false,
  totals,
  onCustomerSelect,
}: CustomerTableProps) {
  const [sort, setSort] = useState<CustomerSort>(defaultSort)
  const [expanded, setExpanded] = useState(false)
  const sorted = useMemo(() => sortCustomerRows(rows, sort), [rows, sort])
  const onSort = useCallback((key: CustomerSortKey) => setSort((s) => nextCustomerSort(s, key)), [])
  const close = useCallback(() => setExpanded(false), [])
  const selectFromModal = useCallback(
    (customer: string) => {
      setExpanded(false)
      onCustomerSelect?.(customer)
    },
    [onCustomerSelect],
  )
  const head = HEAD_CLASS[tone]
  const hint = describeCustomerSort(sort, defaultSort, defaultHint)

  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className={`${head} flex items-center gap-2 px-3 py-2 text-sm font-semibold`}>
        <span>{title}</span>
        {/* Bruno PDF 2026-07-22 Overview R1: customer count at the top. */}
        {showCount && !loading && count !== undefined && (
          <span className="rounded-full bg-white/60 px-2 py-0.5 text-xs font-semibold tabular-nums">
            {count.toLocaleString("en-US")}
          </span>
        )}
        <span className="text-xs font-normal opacity-75" aria-live="polite">· {hint}</span>
        <span className="ml-auto">
          <ExpandButton label={title} onClick={() => setExpanded(true)} />
        </span>
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <CustomerGrid
          rows={sorted}
          totals={totals}
          sort={sort}
          onSort={onSort}
          head={head}
          scrollClass="max-h-[620px]"
          nameClass="max-w-[260px]"
          onCustomerSelect={onCustomerSelect}
        />
      )}
      {expanded && (
        <ExpandModal title={`${title} · ${hint}`} onClose={close}>
          <CapNote shown={rows.length} total={count} />
          <CustomerGrid
            rows={sorted}
            totals={totals}
            sort={sort}
            onSort={onSort}
            head={head}
            scrollClass="max-h-[70vh]"
            nameClass="max-w-[420px]"
            onCustomerSelect={onCustomerSelect ? selectFromModal : undefined}
          />
        </ExpandModal>
      )}
    </div>
  )
}

function CapNote({ shown, total }: { shown: number; total?: number }) {
  const capped = total !== undefined && total > shown
  return (
    <p className="mb-2 text-xs text-[#6B7280]">
      {shown.toLocaleString("en-US")} customer{shown === 1 ? "" : "s"}
      {capped && ` of ${total.toLocaleString("en-US")} (list capped server-side)`}
      {" · click a header to sort · Totals cover every customer"}
    </p>
  )
}

interface CustomerGridProps {
  rows: CeoCustomerRow[]
  totals?: CeoCustomerTotals
  sort: CustomerSort
  onSort: (key: CustomerSortKey) => void
  head: string
  scrollClass: string
  nameClass: string
  onCustomerSelect?: (customer: string) => void
}

function CustomerGrid({
  rows,
  totals,
  sort,
  onSort,
  head,
  scrollClass,
  nameClass,
  onCustomerSelect,
}: CustomerGridProps) {
  return (
    <div className={`${scrollClass} overflow-auto`}>
      <table className="w-full text-[13px] tabular-nums">
        <thead className={`${head} sticky top-0 z-10`}>
          <tr>
            {CUSTOMER_COLUMNS.map((c) => (
              <SortHeader key={c.key} columnKey={c.key} label={c.label} sort={sort} onSort={onSort} />
            ))}
          </tr>
        </thead>
        <tbody>
          <TotalsRow totals={totals} />
          {rows.map((r) => (
            <tr key={r.customer} className="border-t border-[#F3F4F6]">
              <td className="px-2 py-1.5">
                <CustomerLink name={r.customer} onSelect={onCustomerSelect} className={`block truncate ${nameClass}`} />
              </td>
              <td className="px-1 py-1.5 text-right">{fmtCount(r.loads)}</td>
              <td className="px-1 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
              <td className="px-1 py-1.5 text-right">{fmtUsd(r.profit)}</td>
              <td className={`px-1 py-1.5 text-right ${marginCellClass(r.margin_pct)}`}>{fmtPct(r.margin_pct)}</td>
              <td className="px-1 py-1.5 text-right">{fmtPct(r.conc_pct)}</td>
              <td className="px-1 py-1.5 text-right">{fmtUsd(r.avg_p_per_l)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Pinned under the header; rendered apart from the rows so a sort never moves it. */
function TotalsRow({ totals }: { totals?: CeoCustomerTotals }) {
  return (
    <tr className="sticky top-[30px] bg-[#F3F4F6] font-semibold">
      <td className="px-2 py-1.5">Totals</td>
      <td className="px-1 py-1.5 text-right">{totals ? fmtCount(totals.loads) : "—"}</td>
      <td className="px-1 py-1.5 text-right">{totals ? fmtUsd(totals.revenue) : "—"}</td>
      <td className="px-1 py-1.5 text-right">{totals ? fmtUsd(totals.profit) : "—"}</td>
      <td className={`px-1 py-1.5 text-right ${totals ? marginCellClass(totals.margin_pct) : ""}`}>
        {totals ? fmtPct(totals.margin_pct) : "—"}
      </td>
      <td className="px-1 py-1.5 text-right">{totals ? fmtPct(totals.conc_pct) : "—"}</td>
      <td className="px-1 py-1.5 text-right">{totals ? fmtUsd(totals.avg_p_per_l) : "—"}</td>
    </tr>
  )
}

function SortHeader({
  columnKey,
  label,
  sort,
  onSort,
}: {
  columnKey: CustomerSortKey
  label: string
  sort: CustomerSort
  onSort: (key: CustomerSortKey) => void
}) {
  const active = sort.key === columnKey
  const left = columnKey === "customer"
  const Icon = !active ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown
  return (
    <th
      scope="col"
      aria-sort={ariaSortFor(sort, columnKey)}
      className={`${left ? "px-2 text-left" : "px-1 text-right"} py-1.5`}
    >
      <button
        type="button"
        onClick={() => onSort(columnKey)}
        title={`Sort by ${label}`}
        className={`inline-flex items-center gap-1 rounded hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-current ${
          active ? "font-bold" : "font-semibold"
        } ${left ? "" : "flex-row-reverse"}`}
      >
        <span>{label}</span>
        <Icon aria-hidden="true" className={`h-3 w-3 shrink-0 ${active ? "opacity-100" : "opacity-40"}`} />
      </button>
    </th>
  )
}
