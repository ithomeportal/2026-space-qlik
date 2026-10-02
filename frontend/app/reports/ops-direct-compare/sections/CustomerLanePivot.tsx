"use client"

import { Fragment, useState } from "react"
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react"
import { DCErrorBanner } from "../ErrorBanner"
import {
  DC_DEFAULT_SORT,
  useDCPivot,
  type DCPanelFilters,
} from "@/lib/ops-direct-compare-api"
import { Pager } from "./CompareTable"
import {
  ariaSort,
  CompareCells,
  CompareHeaderCells,
  CompareLegend,
  nextSort,
  sortArrow,
  type CompareColumn,
} from "./compareColumns"

const PAGE_SIZE = 200

interface Props {
  title: string
  p1: DCPanelFilters
  p2: DCPanelFilters
  columns: CompareColumn[]
}

/**
 * Customer → Lane pivot (Bruno PDF 2026-10-01 R8): the Details by Lane columns
 * with a Customer column in front; each customer row expands to its lanes.
 * A customer row is the SUM of its lanes (the backend aggregates it from the
 * lane grain), so it also equals that customer's row in Details by Customer.
 * Lanes sort by the same column as the customers.
 */
export function CustomerLanePivot({ title, p1, p2, columns }: Props) {
  const [sort, setSort] = useState(DC_DEFAULT_SORT)
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set())
  const q = useDCPivot(p1, p2, { sort, page, limit: PAGE_SIZE })
  const rows = q.data?.data ?? []
  const meta = q.data?.meta
  const totals = meta?.totals ?? null

  const toggle = (customer: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(customer)) next.delete(customer)
      else next.add(customer)
      return next
    })
  const allOpen = rows.length > 0 && rows.every((r) => open.has(r.customer))
  const toggleAll = () =>
    setOpen(allOpen ? new Set() : new Set(rows.map((r) => r.customer)))
  const changeSort = (next: string) => {
    setSort(next)
    setPage(1)
  }

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <DCErrorBanner errors={[q.error]} label={title} />
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-[#1B3A5C]">{title}</h3>
          <CompareLegend />
          {rows.length > 0 && (
            <button
              type="button"
              onClick={toggleAll}
              className="rounded border border-[#E5E7EB] px-2 py-0.5 text-[10px] text-[#374151] hover:bg-[#F9FAFB]"
            >
              {allOpen ? "Collapse all" : "Expand all"}
            </button>
          )}
        </div>
        <Pager page={page} total={meta?.total ?? 0} unit="customers" onPage={setPage} />
      </div>
      {q.isLoading ? (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[620px] overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-[#E5E7EB] text-[10px] uppercase tracking-wider">
                <th
                  aria-sort={ariaSort(sort, "customer")}
                  className="sticky left-0 z-20 bg-white px-2 py-2 text-left text-[#6B7280]"
                >
                  <button
                    type="button"
                    onClick={() => changeSort(nextSort(sort, "customer"))}
                    className="uppercase tracking-wider hover:underline"
                  >
                    Customer
                    {sortArrow(sort, "customer")}
                  </button>
                </th>
                <th className="bg-white px-2 py-2 text-left text-[#6B7280]">Lane</th>
                <CompareHeaderCells columns={columns} sort={sort} onSort={changeSort} />
              </tr>
              {totals && (
                <tr className="border-b border-[#D1D5DB] font-semibold">
                  <td className="sticky left-0 z-20 bg-[#F9FAFB] px-2 py-1.5 text-[#374151]">
                    Totals
                  </td>
                  <td className="bg-[#F9FAFB]" />
                  <CompareCells row={totals} columns={columns} />
                </tr>
              )}
            </thead>
            <tbody>
              {rows.map((c) => {
                const isOpen = open.has(c.customer)
                return (
                  <Fragment key={c.customer}>
                    <tr className="border-b border-[#E5E7EB] font-medium hover:bg-[#F9FAFB]">
                      <td
                        className="sticky left-0 max-w-[260px] truncate bg-white px-2 py-1.5 text-[#111827]"
                        title={c.customer}
                      >
                        <button
                          type="button"
                          onClick={() => toggle(c.customer)}
                          aria-expanded={isOpen}
                          className="inline-flex max-w-full items-center gap-1 truncate text-left"
                        >
                          {isOpen ? (
                            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[#6B7280]" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[#6B7280]" />
                          )}
                          <span className="truncate">{c.customer}</span>
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-[10px] text-[#6B7280]">
                        {c.lane_count.toLocaleString()} {c.lane_count === 1 ? "lane" : "lanes"}
                      </td>
                      <CompareCells row={c} columns={columns} />
                    </tr>
                    {isOpen &&
                      c.lanes.map((l, idx) => (
                        <tr key={`${c.customer}|${l.lane}|${idx}`} className="border-b border-[#F3F4F6]">
                          <td className="sticky left-0 bg-white" />
                          <td
                            className="max-w-[280px] truncate px-2 py-1 pl-4 text-[#374151]"
                            title={l.lane ?? ""}
                          >
                            {l.lane}
                          </td>
                          <CompareCells row={l} columns={columns} cellClass="px-2 py-1" />
                        </tr>
                      ))}
                  </Fragment>
                )
              })}
              {rows.length === 0 && (
                <tr>
                  <td
                    colSpan={columns.length + 2}
                    className="px-2 py-4 text-center text-[#6B7280]"
                  >
                    No data in either window.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
