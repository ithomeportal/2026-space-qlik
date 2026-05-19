"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react"
import {
  adminCashflowCsvUrl,
  useAging,
  type AdminCashflowFilters,
  type AgingRow,
  type AgingTab,
} from "@/lib/admin-cashflow-api"
import { DownloadCsvButton } from "./DownloadCsvButton"
import { daysBandClass, fmtCount, fmtDate, fmtUsd } from "./format"

interface Props {
  filters: AdminCashflowFilters
}

const PAGE_SIZE = 50

interface TabSpec {
  key: AgingTab
  label: string
  threshold: number
  leftLabel: string
  daysLabel: string
}

// Thresholds match the KPI strip (Bruno R3 PDF 2026-05-19):
// Delivery ≤2d, BOL ≤1d, Carrier Inv ≤1d. C-B direction flipped.
const TABS: TabSpec[] = [
  {
    key: "delivery-vs-bill",
    label: "Delivery → Bill",
    threshold: 2,
    leftLabel: "Dest Departure",
    daysLabel: "bill_date − dest_actual_departure",
  },
  {
    key: "bol-vs-bill",
    label: "BOL → Bill",
    threshold: 1,
    leftLabel: "BOL Recv",
    daysLabel: "bill_date − bol_recv_date",
  },
  {
    key: "carrinv-vs-bill",
    label: "Carrier Inv → Bill (C-B)",
    threshold: 1,
    leftLabel: "Inv Recv",
    daysLabel: "bill_date − invoice_recv_date",
  },
]

export function AgingTabs({ filters }: Props) {
  const [active, setActive] = useState<AgingTab>("delivery-vs-bill")
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<string>("days_desc")

  // Reset page when tab changes
  const switchTab = (k: AgingTab) => {
    setActive(k)
    setPage(1)
    setSort("days_desc")
  }

  const tab = TABS.find((t) => t.key === active)!
  const { data, isLoading } = useAging(active, filters, {
    sort,
    page,
    limit: PAGE_SIZE,
  })
  const rows = (data?.data ?? []) as AgingRow[]
  const total = data?.meta?.total ?? 0
  const le = data?.meta?.le_threshold_count ?? 0
  const gt = data?.meta?.gt_threshold_count ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      {/* Tabs header */}
      <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-[#E5E7EB] pb-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => switchTab(t.key)}
            className={`rounded-md px-3 py-1.5 text-xs ${
              active === t.key
                ? "bg-[#1B3A5C] text-white shadow-sm"
                : "border border-[#E5E7EB] text-[#374151] hover:bg-[#F9FAFB]"
            }`}
          >
            {t.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-3">
          <span className="text-[11px] text-[#6B7280]">
            Days = {tab.daysLabel}
          </span>
          <DownloadCsvButton
            href={adminCashflowCsvUrl(`aging/${active}`, filters, { sort })}
            title={`Download all ${tab.label} rows in current filters as CSV`}
          />
        </div>
      </div>

      {/* Sub-KPI strip (≤threshold / >threshold counts) */}
      <div className="mb-3 grid grid-cols-3 gap-2 text-xs">
        <div className="rounded-md border border-[#E5E7EB] bg-[#F9FAFB] p-2">
          <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            Total
          </div>
          <div className="text-base font-semibold text-[#1B3A5C] tabular-nums">
            {fmtCount(total)}
          </div>
        </div>
        <div className="rounded-md border border-[#A7F3D0] bg-[#ECFDF5] p-2">
          <div className="text-[10px] uppercase tracking-wider text-[#065F46]">
            ≤ {tab.threshold} days
          </div>
          <div className="text-base font-semibold text-[#065F46] tabular-nums">
            {fmtCount(le)}
          </div>
        </div>
        <div className="rounded-md border border-[#FCA5A5] bg-[#FEF2F2] p-2">
          <div className="text-[10px] uppercase tracking-wider text-[#991B1B]">
            &gt; {tab.threshold} days
          </div>
          <div className="text-base font-semibold text-[#991B1B] tabular-nums">
            {fmtCount(gt)}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-auto">
        <table className="w-full text-xs">
          <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            <tr className="border-b border-[#E5E7EB]">
              <th className="px-2 py-1.5 text-left">Co.</th>
              <th className="px-2 py-1.5 text-left">Team</th>
              <SortableTh
                label="Order"
                col="id_asc"
                colDesc="id_desc"
                current={sort}
                onChange={setSort}
              />
              <th className="px-2 py-1.5 text-left">Customer</th>
              <th className="px-2 py-1.5 text-left">{tab.leftLabel}</th>
              <th className="px-2 py-1.5 text-left">Bill Date</th>
              <SortableTh
                label="Days"
                col="days_asc"
                colDesc="days_desc"
                current={sort}
                onChange={setSort}
                align="right"
              />
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
                <td colSpan={8} className="py-10 text-center">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-10 text-center text-[#9CA3AF]">
                  No rows for current filters
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr
                  key={`${r.company_id}-${r.id}`}
                  className="border-b border-[#F3F4F6] last:border-0"
                >
                  <td className="px-2 py-1.5">{r.company_id}</td>
                  <td className="px-2 py-1.5">{r.team_id}</td>
                  <td className="px-2 py-1.5 font-mono text-[11px]">{r.id}</td>
                  <td className="px-2 py-1.5 truncate" title={r.customer_name}>
                    {r.customer_name}
                  </td>
                  <td className="px-2 py-1.5">{fmtDate(r.left_date)}</td>
                  <td className="px-2 py-1.5">{fmtDate(r.bill_date)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    <span
                      className={`rounded px-1.5 py-0.5 ${daysBandClass(
                        r.days,
                        tab.threshold,
                      )}`}
                    >
                      {r.days !== null ? r.days : "—"}
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

      {/* Pager */}
      {total > PAGE_SIZE && (
        <div className="mt-2 flex items-center justify-between text-[11px] text-[#6B7280]">
          <div>
            {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–
            {Math.min(page * PAGE_SIZE, total).toLocaleString()} of{" "}
            {total.toLocaleString()}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page <= 1}
              className="rounded border border-[#E5E7EB] px-2 py-0.5 disabled:opacity-40"
            >
              Prev
            </button>
            <span className="px-1">
              {page} / {pages}
            </span>
            <button
              onClick={() => setPage(Math.min(pages, page + 1))}
              disabled={page >= pages}
              className="rounded border border-[#E5E7EB] px-2 py-0.5 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
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
