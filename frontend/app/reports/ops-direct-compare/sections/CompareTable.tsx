"use client"

import { useState } from "react"
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react"
import { DCErrorBanner } from "../ErrorBanner"
import {
  DC_DEFAULT_SORT,
  useDCCompare,
  type DCCompareDim,
  type DCPanelFilters,
} from "@/lib/ops-direct-compare-api"
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
  dim: DCCompareDim
  p1: DCPanelFilters
  p2: DCPanelFilters
  columns: CompareColumn[]
}

/**
 * "Details by Customer" / "Details by Lane" — one row per customer (lane) with
 * both panels and the Panel 1 − Panel 2 diffs (Bruno PDF 2026-10-01 R6/R7).
 * Sorted and paged on the server; the Totals row is the WHOLE population, not
 * this page. Remount (React `key`) on a filter change resets the page.
 */
export function CompareTable({ title, dim, p1, p2, columns }: Props) {
  const [sort, setSort] = useState(DC_DEFAULT_SORT)
  const [page, setPage] = useState(1)
  const q = useDCCompare(dim, p1, p2, { sort, page, limit: PAGE_SIZE })
  const rows = q.data?.data ?? []
  const meta = q.data?.meta
  const total = meta?.total ?? 0
  const totals = meta?.totals ?? null
  const nameLabel = dim === "customer" ? "Customer" : "Lane"
  const unit = dim === "customer" ? "customers" : "lanes"

  const changeSort = (next: string) => {
    setSort(next)
    setPage(1)
  }

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <DCErrorBanner errors={[q.error]} label={title} />
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-4">
          <h3 className="text-sm font-semibold text-[#1B3A5C]">{title}</h3>
          <CompareLegend />
        </div>
        <Pager page={page} total={total} unit={unit} onPage={setPage} />
      </div>
      {q.isLoading ? (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-[#E5E7EB] text-[10px] uppercase tracking-wider">
                <th
                  aria-sort={ariaSort(sort, dim)}
                  className="sticky left-0 z-20 bg-white px-2 py-2 text-left text-[#6B7280]"
                >
                  <button
                    type="button"
                    onClick={() => changeSort(nextSort(sort, dim))}
                    className="uppercase tracking-wider hover:underline"
                  >
                    {nameLabel}
                    {sortArrow(sort, dim)}
                  </button>
                </th>
                <CompareHeaderCells columns={columns} sort={sort} onSort={changeSort} />
              </tr>
              {totals && (
                <tr className="border-b border-[#D1D5DB] font-semibold">
                  <td className="sticky left-0 z-20 bg-[#F9FAFB] px-2 py-1.5 text-[#374151]">
                    Totals
                  </td>
                  <CompareCells row={totals} columns={columns} />
                </tr>
              )}
            </thead>
            <tbody>
              {rows.map((r, idx) => {
                const name = (dim === "customer" ? r.customer : r.lane) ?? "—"
                return (
                  <tr key={`${name}-${idx}`} className="border-b border-[#F3F4F6]">
                    <td
                      className="sticky left-0 max-w-[260px] truncate bg-white px-2 py-1.5 text-[#111827]"
                      title={name}
                    >
                      {name}
                    </td>
                    <CompareCells row={r} columns={columns} />
                  </tr>
                )
              })}
              {rows.length === 0 && (
                <tr>
                  <td
                    colSpan={columns.length + 1}
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

export function Pager({
  page,
  total,
  unit,
  onPage,
  pageSize = PAGE_SIZE,
}: {
  page: number
  total: number
  unit: string
  onPage: (p: number) => void
  pageSize?: number
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  return (
    <div className="flex items-center gap-2 text-[10px] text-[#6B7280]">
      <span className="tabular-nums">
        {total <= pageSize
          ? `${total.toLocaleString()} ${unit}`
          : `${from.toLocaleString()}–${to.toLocaleString()} of ${total.toLocaleString()} ${unit}`}
      </span>
      {pages > 1 && (
        <>
          <button
            type="button"
            aria-label="Previous page"
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
            className="rounded border border-[#E5E7EB] p-0.5 disabled:opacity-40"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label="Next page"
            disabled={page >= pages}
            onClick={() => onPage(page + 1)}
            className="rounded border border-[#E5E7EB] p-0.5 disabled:opacity-40"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </>
      )}
    </div>
  )
}
