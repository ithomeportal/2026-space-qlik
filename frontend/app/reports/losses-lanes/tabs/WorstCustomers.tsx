"use client"

import { useState } from "react"
import { Loader2, ArrowUpDown } from "lucide-react"
import { useLossesByCustomer, type LossesFilters } from "@/lib/losses-lanes-api"
import { LossesErrorBanner } from "../ErrorBanner"

const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const COUNT = new Intl.NumberFormat("en-US")

const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))
const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT.format(Number(v))

interface Props {
  filters: LossesFilters
}

export function WorstCustomers({ filters }: Props) {
  const [sort, setSort] = useState<string>("profit_asc")
  const [page, setPage] = useState(1)
  const limit = 100

  const { data, isLoading, error } = useLossesByCustomer(filters, sort, page, limit)
  const rows = data?.data ?? []
  const total = data?.meta?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / limit))

  const setSortKey = (key: string) => {
    setSort((prev) => {
      if (prev === `${key}_asc`) return `${key}_desc`
      if (prev === `${key}_desc`) return `${key}_asc`
      return `${key}_asc`
    })
    setPage(1)
  }

  return (
    <div className="space-y-3">
      <LossesErrorBanner errors={[error]} label="Worst Margins by Customer" />
      <div className="flex items-center justify-between">
        <div className="text-xs text-[#6B7280]">
          {total.toLocaleString()} customers with negative-margin loads
        </div>
        {isLoading && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
      </div>
      <div className="overflow-auto rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-[#7F1D1D] text-white">
            <tr>
              <Th label="Customer" onClick={() => setSortKey("customer")} />
              <Th label="# Loads" onClick={() => setSortKey("loads")} right />
              <Th label="Revenue" onClick={() => setSortKey("revenue")} right />
              <Th label="$ Profit" onClick={() => setSortKey("profit")} right />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !isLoading && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-[#6B7280]">
                  No losing customers in this window.
                </td>
              </tr>
            )}
            {rows.map((r, i) => (
              <tr
                key={`${r.customer ?? ""}-${i}`}
                className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]"
              >
                <td className="px-2 py-1.5 font-medium text-[#111827]">{r.customer ?? "—"}</td>
                <td className="px-2 py-1.5 text-right">{fmtCount(r.loads)}</td>
                <td className="px-2 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                <td className="px-2 py-1.5 text-right font-semibold text-[#B91C1C]">
                  {fmtUsd(r.profit)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > limit && (
        <div className="flex items-center justify-between text-xs">
          <div className="text-[#6B7280]">
            Page {page} of {pageCount} · {total.toLocaleString()} customers
          </div>
          <div className="flex gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="rounded border border-[#E5E7EB] bg-white px-3 py-1 disabled:opacity-40"
            >
              Prev
            </button>
            <button
              onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
              disabled={page === pageCount}
              className="rounded border border-[#E5E7EB] bg-white px-3 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function Th({
  label,
  onClick,
  right,
}: {
  label: string
  onClick?: () => void
  right?: boolean
}) {
  return (
    <th
      onClick={onClick}
      className={`cursor-pointer px-2 py-2 font-semibold hover:bg-[#991B1B] ${right ? "text-right" : "text-left"}`}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {onClick && <ArrowUpDown className="h-3 w-3 opacity-60" />}
      </span>
    </th>
  )
}
