"use client"

import { useState } from "react"
import { Loader2, ArrowUpDown, X } from "lucide-react"
import { useLossesOrders, type LossesFilters } from "@/lib/losses-lanes-api"
import { LossesErrorBanner } from "../ErrorBanner"

const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const PCT2 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
})

const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))
const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT2.format(Number(v))}%`

interface Props {
  filters: LossesFilters
  lane?: string
  onClearLane: () => void
}

export function OrderDetails({ filters, lane, onClearLane }: Props) {
  const [sort, setSort] = useState<string>("date_desc")
  const [page, setPage] = useState(1)
  const limit = 100

  const { data, isLoading, error } = useLossesOrders(filters, sort, page, limit, lane)
  const rows = data?.data ?? []
  const total = data?.meta?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / limit))

  const setSortKey = (key: string) => {
    setSort((prev) => {
      if (prev === `${key}_desc`) return `${key}_asc`
      if (prev === `${key}_asc`) return `${key}_desc`
      return `${key}_desc`
    })
    setPage(1)
  }

  return (
    <div className="space-y-3">
      <LossesErrorBanner errors={[error]} label="Order Details" />
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 text-xs text-[#6B7280]">
          <span>{total.toLocaleString()} losing orders</span>
          {lane && (
            <span className="inline-flex items-center gap-1 rounded-full bg-[#FEE2E2] px-2 py-0.5 text-[#991B1B]">
              Lane filter: <strong>{lane}</strong>
              <button
                onClick={onClearLane}
                className="ml-1 rounded hover:bg-[#FECACA]"
                title="Clear lane filter"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          )}
        </div>
        {isLoading && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
      </div>
      <div className="overflow-auto rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-[#7F1D1D] text-white">
            <tr>
              <Th label="Actual Day" onClick={() => setSortKey("date")} />
              <th className="px-2 py-2 text-left font-semibold">ID</th>
              <th className="px-2 py-2 text-left font-semibold">Customer ID</th>
              <th className="px-2 py-2 text-left font-semibold">Customer</th>
              <th className="px-2 py-2 text-left font-semibold">Origin</th>
              <th className="px-2 py-2 text-left font-semibold">Destination</th>
              <Th label="Revenue" onClick={() => setSortKey("revenue")} right />
              <Th label="$ Profit" onClick={() => setSortKey("profit")} right />
              <Th label="% Margin" onClick={() => setSortKey("margin")} right />
              <th className="px-2 py-2 text-left font-semibold">Type</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !isLoading && (
              <tr>
                <td colSpan={10} className="px-4 py-8 text-center text-[#6B7280]">
                  No losing orders in this window.
                </td>
              </tr>
            )}
            {rows.map((r, i) => (
              <tr
                key={`${r.id ?? ""}-${i}`}
                className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]"
              >
                <td className="px-2 py-1.5 text-[#374151]">{r.actual_day ?? "—"}</td>
                <td className="px-2 py-1.5 font-mono text-[#111827]">{r.id ?? "—"}</td>
                <td className="px-2 py-1.5 text-[#374151]">{r.customer_id ?? "—"}</td>
                <td className="px-2 py-1.5 text-[#374151]">{r.customer_name ?? "—"}</td>
                <td className="px-2 py-1.5 text-[#374151]">{r.origin ?? "—"}</td>
                <td className="px-2 py-1.5 text-[#374151]">{r.destination ?? "—"}</td>
                <td className="px-2 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                <td className="px-2 py-1.5 text-right font-semibold text-[#B91C1C]">
                  {fmtUsd(r.profit)}
                </td>
                <td className="px-2 py-1.5 text-right font-semibold text-[#7C3AED]">
                  {fmtPct(r.margin_pct)}
                </td>
                <td className="px-2 py-1.5 text-[#374151]">{r.contract_type ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > limit && (
        <div className="flex items-center justify-between text-xs">
          <div className="text-[#6B7280]">
            Page {page} of {pageCount} · {total.toLocaleString()} orders
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
