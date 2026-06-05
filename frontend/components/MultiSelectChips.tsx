"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { ChevronDown, X } from "lucide-react"

export type FilterMode = "include" | "exclude"

interface Props {
  label: string
  options: string[]
  selected: string[]
  onChange: (next: string[]) => void
  placeholder?: string
  width?: number
  disabled?: boolean
  /** Optional Include⇄Exclude toggle (Ops Portal Overview R7 Lane filter).
   *  Omit both props to keep the plain include-only picker (XRay DFW). */
  mode?: FilterMode
  onModeChange?: (next: FilterMode) => void
}

/**
 * Compact, pure-React/HTML multi-select used in the XRay DFW filter strip
 * (Bruno 2026-05-28). No Base UI / cmdk — see CLAUDE.md "Search bar is pure
 * React/HTML". When nothing is selected the trigger reads "All …" and the
 * backend treats the empty array as "no filter" (so the include/exclude mode
 * is irrelevant until at least one option is checked).
 */
export function MultiSelectChips({
  label,
  options,
  selected,
  onChange,
  placeholder,
  width = 220,
  disabled = false,
  mode,
  onModeChange,
}: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const boxRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [open])

  const lowerQuery = query.trim().toLowerCase()
  const filtered = useMemo(() => {
    if (!lowerQuery) return options.slice(0, 300)
    return options.filter((o) => o.toLowerCase().includes(lowerQuery)).slice(0, 300)
  }, [options, lowerQuery])

  const selectedSet = useMemo(() => new Set(selected), [selected])
  const summary =
    selected.length === 0
      ? placeholder ?? `All ${label.toLowerCase()}s`
      : selected.length === 1
        ? selected[0]
        : `${selected.length} selected`

  const toggle = (id: string) => {
    if (selectedSet.has(id)) onChange(selected.filter((x) => x !== id))
    else onChange([...selected, id])
  }

  return (
    <div ref={boxRef} className="relative inline-flex items-center gap-1.5">
      <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </label>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        style={{ width }}
        className={`flex items-center justify-between gap-2 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-left text-xs text-[#111827] shadow-sm hover:bg-[#F9FAFB] focus:border-[#1B3A5C] focus:outline-none ${
          disabled ? "cursor-not-allowed bg-[#F9FAFB] text-[#9CA3AF]" : ""
        }`}
      >
        <span className="flex min-w-0 items-center gap-1.5">
          {selected.length > 0 && (
            <span
              className={`shrink-0 rounded-full px-1.5 py-px text-[10px] font-semibold ${
                mode === "exclude"
                  ? "bg-[#FEE2E2] text-[#991B1B]"
                  : "bg-[#DBEAFE] text-[#1D4ED8]"
              }`}
            >
              {onModeChange ? `${mode === "exclude" ? "excl" : "incl"} ${selected.length}` : selected.length}
            </span>
          )}
          <span className="truncate">{summary}</span>
        </span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[#6B7280]" />
      </button>

      {selected.length > 0 && (
        <button
          type="button"
          onClick={() => onChange([])}
          title="Clear"
          className="rounded-md border border-[#E5E7EB] bg-white p-1 text-[#6B7280] hover:bg-[#F3F4F6]"
        >
          <X className="h-3 w-3" />
        </button>
      )}

      {open && (
        <div
          style={{ width: width + 40 }}
          className="absolute left-0 top-full z-30 mt-1 rounded-md border border-[#E5E7EB] bg-white shadow-lg"
        >
          {onModeChange && (
            <div className="flex items-center gap-1 border-b border-[#F3F4F6] px-1.5 py-1.5">
              <div className="inline-flex rounded-full bg-[#F3F4F6] p-0.5 text-[11px] font-medium">
                <button
                  type="button"
                  onClick={() => onModeChange("include")}
                  className={`rounded-full px-2.5 py-0.5 transition ${
                    mode !== "exclude"
                      ? "bg-[#1D4ED8] text-white shadow-sm"
                      : "text-[#374151] hover:text-[#111827]"
                  }`}
                >
                  Include
                </button>
                <button
                  type="button"
                  onClick={() => onModeChange("exclude")}
                  className={`rounded-full px-2.5 py-0.5 transition ${
                    mode === "exclude"
                      ? "bg-[#991B1B] text-white shadow-sm"
                      : "text-[#374151] hover:text-[#111827]"
                  }`}
                >
                  Exclude
                </button>
              </div>
            </div>
          )}
          <div className="border-b border-[#F3F4F6] p-1.5">
            <input
              autoFocus
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Search ${label.toLowerCase()}…`}
              className="w-full rounded border border-[#E5E7EB] px-2 py-1 text-xs focus:border-[#1B3A5C] focus:outline-none"
            />
          </div>
          <ul className="max-h-64 overflow-auto py-1 text-xs">
            {filtered.length === 0 && (
              <li className="px-3 py-2 text-[#9CA3AF]">No matches</li>
            )}
            {filtered.map((o) => {
              const on = selectedSet.has(o)
              return (
                <li key={o}>
                  <button
                    type="button"
                    onClick={() => toggle(o)}
                    className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-[#F3F4F6]"
                  >
                    <span
                      className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded border ${
                        on
                          ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                          : "border-[#D1D5DB] bg-white"
                      }`}
                    >
                      {on && (
                        <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none">
                          <path
                            d="M2.5 6.5l2.5 2.5 4.5-5"
                            stroke="currentColor"
                            strokeWidth="1.6"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      )}
                    </span>
                    <span className="truncate">{o}</span>
                  </button>
                </li>
              )
            })}
          </ul>
          {selected.length > 0 && (
            <div className="flex items-center justify-between border-t border-[#F3F4F6] px-2.5 py-1.5 text-[10px] text-[#6B7280]">
              <span>{selected.length} selected</span>
              <button
                type="button"
                onClick={() => onChange([])}
                className="font-semibold text-[#1D4ED8] hover:underline"
              >
                Clear all
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
