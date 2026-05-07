"use client"

import { useMemo, useState } from "react"
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"

type SortDir = "asc" | "desc"

export function useSortable<T>(
  rows: T[],
  initialKey?: keyof T,
  initialDir: SortDir = "desc",
) {
  const [sortKey, setSortKey] = useState<keyof T | undefined>(initialKey)
  const [sortDir, setSortDir] = useState<SortDir>(initialDir)

  const sorted = useMemo(() => {
    if (!sortKey) return rows
    const out = [...rows]
    out.sort((a, b) => {
      const av = (a as Record<keyof T, unknown>)[sortKey]
      const bv = (b as Record<keyof T, unknown>)[sortKey]
      // null / undefined sort to the end regardless of direction
      if (av === null || av === undefined) return 1
      if (bv === null || bv === undefined) return -1
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av
      }
      const as = String(av).toLowerCase()
      const bs = String(bv).toLowerCase()
      if (as < bs) return sortDir === "asc" ? -1 : 1
      if (as > bs) return sortDir === "asc" ? 1 : -1
      return 0
    })
    return out
  }, [rows, sortKey, sortDir])

  function toggle(key: keyof T) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  return { sorted, sortKey, sortDir, toggle }
}

export function SortableTh<T>({
  columnKey,
  sortKey,
  sortDir,
  onToggle,
  align = "right",
  children,
}: {
  columnKey: keyof T
  sortKey: keyof T | undefined
  sortDir: SortDir
  onToggle: (key: keyof T) => void
  align?: "left" | "right"
  children: React.ReactNode
}) {
  const active = sortKey === columnKey
  const Icon = !active ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown
  return (
    <th className={`px-1 py-1 ${align === "left" ? "text-left" : "text-right"}`}>
      <button
        onClick={() => onToggle(columnKey)}
        className={`inline-flex items-center gap-1 hover:underline ${active ? "font-bold" : ""}`}
      >
        {align === "right" ? (
          <>
            <Icon className={`h-3 w-3 ${active ? "opacity-100" : "opacity-40"}`} />
            <span>{children}</span>
          </>
        ) : (
          <>
            <span>{children}</span>
            <Icon className={`h-3 w-3 ${active ? "opacity-100" : "opacity-40"}`} />
          </>
        )}
      </button>
    </th>
  )
}
