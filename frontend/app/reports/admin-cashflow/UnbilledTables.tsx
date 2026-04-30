"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp, Loader2, Package, Stamp } from "lucide-react"
import {
  useDeliveredNotBilled,
  useReadyNotBilled,
  type AdminCashflowFilters,
  type DeliveredNotBilledRow,
  type ReadyNotBilledRow,
} from "@/lib/admin-cashflow-api"
import { fmtCount, fmtDate, fmtUsd } from "./format"

interface Props {
  filters: AdminCashflowFilters
}

const PAGE_SIZE = 25

export function UnbilledTables({ filters }: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <DeliveredNotBilledCard filters={filters} />
      <ReadyNotBilledCard filters={filters} />
    </div>
  )
}

function DeliveredNotBilledCard({ filters }: Props) {
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<string>("delivered_asc")
  const { data, isLoading } = useDeliveredNotBilled(filters, {
    sort,
    page,
    limit: PAGE_SIZE,
  })
  const rows = data?.data ?? []
  const total = data?.meta?.total ?? 0
  const grand = data?.meta?.grand_total_revenue ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <Package className="h-4 w-4 text-[#B45309]" />
          <div className="text-sm font-semibold text-[#1B3A5C]">
            Delivered but not billed
          </div>
        </div>
        <div className="text-xs text-[#6B7280]">
          {fmtCount(total)} loads · {fmtUsd(grand)}
        </div>
      </div>
      <div className="overflow-auto">
        <table className="w-full text-xs">
          <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            <tr className="border-b border-[#E5E7EB]">
              <SortableTh
                label="Order"
                col="id_asc"
                colDesc="id_desc"
                current={sort}
                onChange={setSort}
              />
              <SortableTh
                label="Orig Sched Early"
                col="ship_asc"
                colDesc="ship_desc"
                current={sort}
                onChange={setSort}
              />
              <SortableTh
                label="Ship Date"
                col="ship_asc"
                colDesc="ship_desc"
                current={sort}
                onChange={setSort}
              />
              <SortableTh
                label="Delivered"
                col="delivered_asc"
                colDesc="delivered_desc"
                current={sort}
                onChange={setSort}
              />
              <th className="px-2 py-1.5 text-right">Days</th>
              <SortableTh
                label="$ Revenue"
                col="revenue_asc"
                colDesc="revenue_desc"
                current={sort}
                onChange={setSort}
                align="right"
              />
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={6} className="py-8 text-center">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-8 text-center text-[#9CA3AF]">
                  No delivered-but-unbilled loads in current filters 🎉
                </td>
              </tr>
            ) : (
              rows.map((r: DeliveredNotBilledRow) => (
                <tr
                  key={`${r.company_id}-${r.id}`}
                  className="border-b border-[#F3F4F6] last:border-0"
                >
                  <td className="px-2 py-1.5 font-mono text-[11px]">{r.id}</td>
                  <td className="px-2 py-1.5">{fmtDate(r.orig_sched_early)}</td>
                  <td className="px-2 py-1.5">{fmtDate(r.ship_date)}</td>
                  <td className="px-2 py-1.5">
                    {fmtDate(r.dest_actual_arrival)}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {r.days_since_delivery !== null ? (
                      <span
                        className={`rounded px-1.5 py-0.5 text-[11px] ${
                          r.days_since_delivery <= 3
                            ? "text-[#065F46] bg-[#ECFDF5]"
                            : r.days_since_delivery <= 7
                            ? "text-[#92400E] bg-[#FEF3C7]"
                            : "text-[#991B1B] bg-[#FEE2E2] font-semibold"
                        }`}
                      >
                        {r.days_since_delivery}d
                      </span>
                    ) : (
                      <span className="text-[#9CA3AF]">—</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {fmtUsd(r.total_charge)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <Pager
        page={page}
        pages={pages}
        total={total}
        onChange={setPage}
        size={PAGE_SIZE}
      />
    </div>
  )
}

function ReadyNotBilledCard({ filters }: Props) {
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<string>("ship_asc")
  const { data, isLoading } = useReadyNotBilled(filters, {
    sort,
    page,
    limit: PAGE_SIZE,
  })
  const rows = data?.data ?? []
  const total = data?.meta?.total ?? 0
  const grand = data?.meta?.grand_total_revenue ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <Stamp className="h-4 w-4 text-[#B45309]" />
          <div className="text-sm font-semibold text-[#1B3A5C]">
            Ready to bill but not billed
          </div>
        </div>
        <div className="text-xs text-[#6B7280]">
          {fmtCount(total)} loads · {fmtUsd(grand)}
        </div>
      </div>
      <div className="overflow-auto">
        <table className="w-full text-xs">
          <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            <tr className="border-b border-[#E5E7EB]">
              <SortableTh
                label="Order"
                col="id_asc"
                colDesc="id_desc"
                current={sort}
                onChange={setSort}
              />
              <SortableTh
                label="Ship Date"
                col="ship_asc"
                colDesc="ship_desc"
                current={sort}
                onChange={setSort}
              />
              <SortableTh
                label="Orig Sched Early"
                col="ship_asc"
                colDesc="ship_desc"
                current={sort}
                onChange={setSort}
              />
              <th className="px-2 py-1.5">Status</th>
              <SortableTh
                label="$ Revenue"
                col="revenue_asc"
                colDesc="revenue_desc"
                current={sort}
                onChange={setSort}
                align="right"
              />
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={5} className="py-8 text-center">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-8 text-center text-[#9CA3AF]">
                  No ready-but-unbilled loads in current filters 🎉
                </td>
              </tr>
            ) : (
              rows.map((r: ReadyNotBilledRow) => (
                <tr
                  key={`${r.company_id}-${r.id}`}
                  className="border-b border-[#F3F4F6] last:border-0"
                >
                  <td className="px-2 py-1.5 font-mono text-[11px]">{r.id}</td>
                  <td className="px-2 py-1.5">{fmtDate(r.ship_date)}</td>
                  <td className="px-2 py-1.5">{fmtDate(r.orig_sched_early)}</td>
                  <td className="px-2 py-1.5">
                    <span className="rounded bg-[#F3F4F6] px-1.5 py-0.5 text-[10px] text-[#374151]">
                      {r.status}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {fmtUsd(r.total_charge)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <Pager
        page={page}
        pages={pages}
        total={total}
        onChange={setPage}
        size={PAGE_SIZE}
      />
    </div>
  )
}

interface SortableThProps {
  label: string
  col: string
  colDesc: string
  current: string
  onChange: (s: string) => void
  align?: "left" | "right"
}

function SortableTh({
  label,
  col,
  colDesc,
  current,
  onChange,
  align = "left",
}: SortableThProps) {
  const active = current === col || current === colDesc
  const isDesc = current === colDesc
  const next = current === col ? colDesc : col
  return (
    <th
      className={`px-2 py-1.5 ${align === "right" ? "text-right" : "text-left"}`}
    >
      <button
        onClick={() => onChange(next)}
        className={`inline-flex items-center gap-1 ${
          active ? "text-[#1B3A5C]" : "text-[#6B7280]"
        }`}
      >
        {label}
        {active &&
          (isDesc ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronUp className="h-3 w-3" />
          ))}
      </button>
    </th>
  )
}

interface PagerProps {
  page: number
  pages: number
  total: number
  size: number
  onChange: (p: number) => void
}

function Pager({ page, pages, total, size, onChange }: PagerProps) {
  if (total <= size) return null
  const first = (page - 1) * size + 1
  const last = Math.min(page * size, total)
  return (
    <div className="mt-2 flex items-center justify-between text-[11px] text-[#6B7280]">
      <div>
        {first.toLocaleString()}–{last.toLocaleString()} of{" "}
        {total.toLocaleString()}
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onChange(Math.max(1, page - 1))}
          disabled={page <= 1}
          className="rounded border border-[#E5E7EB] px-2 py-0.5 disabled:opacity-40"
        >
          Prev
        </button>
        <span className="px-1">
          {page} / {pages}
        </span>
        <button
          onClick={() => onChange(Math.min(pages, page + 1))}
          disabled={page >= pages}
          className="rounded border border-[#E5E7EB] px-2 py-0.5 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  )
}
