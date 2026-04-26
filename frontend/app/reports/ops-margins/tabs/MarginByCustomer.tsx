"use client"

import { useMemo, useState } from "react"
import { Loader2, ArrowUpDown } from "lucide-react"
import {
  useOpsCustomerSpark,
  useOpsCustomersMargin,
  type OpsFilters,
} from "@/lib/ops-margins-api"
import { OpsErrorBanner } from "../ErrorBanner"
import { fmtCount, fmtPct, fmtUsd, marginBgColor, marginColor } from "../format"
import { Sparkline } from "./Sparkline"

interface Props {
  filters: OpsFilters
}

export function MarginByCustomer({ filters }: Props) {
  const [sort, setSort] = useState("margin_desc")
  const [page, setPage] = useState(1)
  const limit = 100

  const { data, isLoading, error } = useOpsCustomersMargin(filters, sort, page, limit)
  const rows = useMemo(() => data?.data ?? [], [data])
  const total = data?.meta?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / limit))

  const customerNames = useMemo(
    () => rows.map((r) => r.customer ?? "").filter((n) => n),
    [rows],
  )
  const sparkRes = useOpsCustomerSpark(filters, customerNames, 8)
  const sparks = sparkRes.data?.data ?? {}

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
      <OpsErrorBanner errors={[error]} label="Margin by Customer" />
      <div className="flex items-center justify-between text-xs text-[#6B7280]">
        <div>{total.toLocaleString()} customers · sorted by best margin first</div>
        <div className="flex items-center gap-2">
          {sparkRes.isLoading && <span className="text-[#9CA3AF]">loading sparklines…</span>}
          <span>Page {page} / {pageCount}</span>
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="rounded border border-[#E5E7EB] bg-white px-2 py-0.5 text-[#374151] disabled:opacity-50"
          >
            ‹
          </button>
          <button
            disabled={page >= pageCount}
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            className="rounded border border-[#E5E7EB] bg-white px-2 py-0.5 text-[#374151] disabled:opacity-50"
          >
            ›
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
        <table className="min-w-full text-xs">
          <thead className="bg-[#F9FAFB] text-[#374151]">
            <tr>
              <Th>Customer</Th>
              <Th onClick={() => setSortKey("lanes")} sortable>
                # Lanes <ArrowUpDown className="inline h-3 w-3" />
              </Th>
              <Th onClick={() => setSortKey("loads")} sortable>
                Loads <ArrowUpDown className="inline h-3 w-3" />
              </Th>
              <Th>Revenue</Th>
              <Th>$ Profit</Th>
              <Th onClick={() => setSortKey("margin")} sortable>
                Margin % <ArrowUpDown className="inline h-3 w-3" />
              </Th>
              <Th>8-wk trend</Th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-[#6B7280]">
                  <Loader2 className="inline h-4 w-4 animate-spin" />
                </td>
              </tr>
            )}
            {!isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-[#6B7280]">
                  No data in window.
                </td>
              </tr>
            )}
            {rows.map((r, i) => {
              const points = sparks[r.customer ?? ""] ?? []
              const sparkValues = points.map((p) => p.margin_pct)
              return (
                <tr key={`${r.customer}-${i}`} className="border-t border-[#F3F4F6]">
                  <Td className="max-w-xs truncate font-medium text-[#111827]">
                    {r.customer ?? "—"}
                  </Td>
                  <Td className="text-right">{fmtCount(r.lane_count)}</Td>
                  <Td className="text-right">{fmtCount(r.loads)}</Td>
                  <Td className="text-right">{fmtUsd(r.revenue)}</Td>
                  <Td className="text-right">{fmtUsd(r.profit)}</Td>
                  <Td
                    className={`text-right font-semibold ${marginColor(
                      r.margin_pct,
                    )} ${marginBgColor(r.margin_pct)}`}
                  >
                    {fmtPct(r.margin_pct)}
                  </Td>
                  <Td>
                    <Sparkline values={sparkValues} />
                  </Td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Th({
  children,
  onClick,
  sortable,
}: {
  children: React.ReactNode
  onClick?: () => void
  sortable?: boolean
}) {
  return (
    <th
      className={`px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider ${
        sortable ? "cursor-pointer hover:text-[#111827]" : ""
      }`}
      onClick={onClick}
    >
      {children}
    </th>
  )
}

function Td({
  children,
  className = "",
}: {
  children: React.ReactNode
  className?: string
}) {
  return <td className={`px-3 py-2 ${className}`}>{children}</td>
}
