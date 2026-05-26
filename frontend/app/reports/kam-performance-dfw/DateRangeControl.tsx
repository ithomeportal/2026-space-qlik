"use client"

import { useMemo, useState } from "react"
import { kamBounds, type KamBounds, type KamRange } from "@/lib/kam-performance-dfw-api"

const PRESETS: { k: KamRange; label: string }[] = [
  { k: "ytd", label: "YTD" },
  { k: "mtd", label: "MTD" },
  { k: "wtd", label: "WTD" },
  { k: "custom", label: "Custom" },
]

export interface DateRangeValue {
  range: KamRange
  start: string
  end: string
}

/**
 * State + resolved bounds for a date-range filter. `defaultRange` seeds the
 * preset; the custom start/end are pre-filled with that preset's window so
 * switching to Custom starts from a sensible window instead of blanks.
 */
export function useKamDateRange(defaultRange: KamRange = "mtd"): {
  value: DateRangeValue
  setValue: (v: DateRangeValue) => void
  bounds: KamBounds
} {
  const seed = kamBounds(defaultRange)
  const [value, setValue] = useState<DateRangeValue>({
    range: defaultRange,
    start: seed.start,
    end: seed.end,
  })
  const bounds = useMemo(
    () => kamBounds(value.range, value.start, value.end),
    [value.range, value.start, value.end],
  )
  return { value, setValue, bounds }
}

/**
 * YTD / MTD / WTD / Custom selector shared by the Service, Lanes, Worst-Lanes
 * and Carrier-Sales tabs (Bruno R2). When `custom` is active two date inputs
 * appear; otherwise the preset drives the window client-side.
 */
export function DateRangeControl({
  value,
  onChange,
}: {
  value: DateRangeValue
  onChange: (next: DateRangeValue) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="inline-flex overflow-hidden rounded-md border border-[#E5E7EB]">
        {PRESETS.map((p) => (
          <button
            key={p.k}
            onClick={() => onChange({ ...value, range: p.k })}
            className={`px-3 py-1.5 text-xs ${
              value.range === p.k
                ? "bg-[#1B3A5C] text-white"
                : "bg-white text-[#374151] hover:bg-[#F9FAFB]"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>
      {value.range === "custom" && (
        <div className="flex items-center gap-1.5">
          <input
            type="date"
            value={value.start}
            max={value.end || undefined}
            onChange={(e) => onChange({ ...value, start: e.target.value })}
            className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs"
          />
          <span className="text-xs text-[#9CA3AF]">→</span>
          <input
            type="date"
            value={value.end}
            min={value.start || undefined}
            onChange={(e) => onChange({ ...value, end: e.target.value })}
            className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs"
          />
        </div>
      )}
    </div>
  )
}
