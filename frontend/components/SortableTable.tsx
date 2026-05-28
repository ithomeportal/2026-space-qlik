"use client"

import { useMemo, useState } from "react"

export type SortDir = "asc" | "desc"

export interface SortState {
  sortKey: string | null
  sortDir: SortDir
  toggleSort: (key: string) => void
}

function isEmpty(v: unknown): boolean {
  return v === null || v === undefined || v === ""
}

function compareValues(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a - b
  return String(a).localeCompare(String(b), undefined, { numeric: true })
}

/**
 * Generic client-side table sorting (Bruno 2026-05-28: sortable columns on
 * every XRay DFW tab). Empty/null values always sort last regardless of
 * direction. Clicking the active column flips the direction.
 */
export function useSortable<T>(
  rows: T[],
  defaultKey: string | null = null,
  defaultDir: SortDir = "desc",
): { sorted: T[] } & SortState {
  const [sortKey, setSortKey] = useState<string | null>(defaultKey)
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir)

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  const sorted = useMemo(() => {
    if (!sortKey) return rows
    const copy = [...rows]
    copy.sort((a, b) => {
      const av = (a as Record<string, unknown>)[sortKey]
      const bv = (b as Record<string, unknown>)[sortKey]
      const ae = isEmpty(av)
      const be = isEmpty(bv)
      if (ae && be) return 0
      if (ae) return 1
      if (be) return -1
      const c = compareValues(av, bv)
      return sortDir === "asc" ? c : -c
    })
    return copy
  }, [rows, sortKey, sortDir])

  return { sorted, sortKey, sortDir, toggleSort }
}

interface SortableThProps {
  label: React.ReactNode
  columnKey: string
  state: SortState
  align?: "left" | "right"
  className?: string
}

/** Clickable table header with an asc/desc indicator. */
export function SortableTh({
  label,
  columnKey,
  state,
  align = "left",
  className = "",
}: SortableThProps) {
  const active = state.sortKey === columnKey
  const arrow = active ? (state.sortDir === "asc" ? "▲" : "▼") : ""
  const justify = align === "right" ? "justify-end" : "justify-start"
  return (
    <th
      className={`px-3 py-1.5 font-semibold ${align === "right" ? "text-right" : "text-left"} ${className}`}
    >
      <button
        type="button"
        onClick={() => state.toggleSort(columnKey)}
        className={`flex w-full items-center gap-1 ${justify} hover:text-[#111827] ${
          active ? "text-[#1B3A5C]" : ""
        }`}
        title="Sort"
      >
        <span>{label}</span>
        <span className="text-[9px] leading-none text-[#9CA3AF]">{arrow || "↕"}</span>
      </button>
    </th>
  )
}
