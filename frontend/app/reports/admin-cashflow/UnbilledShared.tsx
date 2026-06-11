"use client"

import { useEffect } from "react"
import { ChevronDown, ChevronUp, Search, X } from "lucide-react"

// ---------------------------------------------------------------------------
// Shared primitives for the two "unbilled" tables (Delivered / Ready).
// Bruno Aging R2 + R3 (2026-06-11): per-column free-text filters + an
// expand-to-pop-up view. Kept here so both cards render identical chrome.
// ---------------------------------------------------------------------------

// Bruno R3: expand-to-pop-up overlay. Plain fixed overlay (no Base UI / Radix)
// to stay React-18 safe, matching the XRay WeeklyPerformanceModal idiom.
export function UnbilledExpandModal({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string
  subtitle?: string
  onClose: () => void
  children: React.ReactNode
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-[#E5E7EB] bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-[#E5E7EB] px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-[#1B3A5C]">{title}</div>
            {subtitle && (
              <div className="mt-0.5 text-xs text-[#6B7280]">{subtitle}</div>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-[#6B7280] hover:bg-[#F3F4F6] hover:text-[#1B3A5C]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4">{children}</div>
      </div>
    </div>
  )
}

// Bruno R2: two small free-text inputs above the table (Order + Customer).
export function ColumnFilters({
  orderQ,
  customerQ,
  onOrder,
  onCustomer,
}: {
  orderQ: string
  customerQ: string
  onOrder: (v: string) => void
  onCustomer: (v: string) => void
}) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2">
      <FilterInput
        placeholder="Filter Order…"
        value={orderQ}
        onChange={onOrder}
      />
      <FilterInput
        placeholder="Filter Customer…"
        value={customerQ}
        onChange={onCustomer}
      />
    </div>
  )
}

function FilterInput({
  placeholder,
  value,
  onChange,
}: {
  placeholder: string
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[#9CA3AF]" />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-44 rounded-md border border-[#E5E7EB] bg-white py-1 pl-7 pr-6 text-xs text-[#374151] placeholder:text-[#9CA3AF] focus:border-[#1B3A5C] focus:outline-none"
      />
      {value && (
        <button
          onClick={() => onChange("")}
          aria-label="Clear"
          className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[#9CA3AF] hover:text-[#374151]"
        >
          <X className="h-3 w-3" />
        </button>
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

export function SortableTh({
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

export function DaysBadge({ days }: { days: number | null | undefined }) {
  if (days === null || days === undefined) {
    return <span className="text-[#9CA3AF]">—</span>
  }
  const cls =
    days <= 3
      ? "text-[#065F46] bg-[#ECFDF5]"
      : days <= 7
      ? "text-[#92400E] bg-[#FEF3C7]"
      : "text-[#991B1B] bg-[#FEE2E2] font-semibold"
  return <span className={`rounded px-1.5 py-0.5 text-[11px] ${cls}`}>{days}d</span>
}

interface PagerProps {
  page: number
  pages: number
  total: number
  size: number
  onChange: (p: number) => void
}

export function Pager({ page, pages, total, size, onChange }: PagerProps) {
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
