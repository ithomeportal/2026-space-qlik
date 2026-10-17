"use client"

import { useEffect, useState } from "react"
import { Search } from "lucide-react"
import { MultiSelectChips } from "@/components/MultiSelectChips"
import { useDebounce } from "@/lib/use-debounce"
import type {
  AugieFilterOptions,
  AugieFunnelRange,
  AugieFunnelUnit,
} from "@/lib/augie-funnel-api"
import { Toggle } from "./Ui"

export const RANGES: { k: AugieFunnelRange; label: string }[] = [
  { k: "today", label: "Today" },
  { k: "last7", label: "Last 7 days" },
  { k: "last30", label: "Last 30 days" },
  { k: "last90", label: "Last 3 months" },
  { k: "upcoming", label: "Upcoming" },
  { k: "custom", label: "Custom range" },
]

export interface FilterState {
  range: AugieFunnelRange
  startDate: string
  endDate: string
  unit: AugieFunnelUnit | ""
  team: string
  customer: string[]
  carrier: string[]
  q: string
}

interface Props {
  value: FilterState
  options: AugieFilterOptions | undefined
  onChange: (patch: Partial<FilterState>) => void
}

const SELECT_CLS =
  "rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs text-[#111827] shadow-sm focus:border-[#1B3A5C] focus:outline-none"

/** Search box: local text, debounced 300 ms before it reaches the URL/query. */
function SearchBox({ value, onCommit }: { value: string; onCommit: (q: string) => void }) {
  const [text, setText] = useState(value)
  const debounced = useDebounce(text, 300)

  // An external change (back button, cleared URL) must reach the box.
  useEffect(() => setText(value), [value])

  useEffect(() => {
    if (debounced.trim() !== value.trim()) onCommit(debounced)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced])

  return (
    <div className="relative min-w-[240px] flex-1">
      <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#9CA3AF]" />
      <input
        type="search"
        value={text}
        maxLength={80}
        onChange={(e) => setText(e.target.value)}
        placeholder="Search by order ID, customer, carrier, team..."
        className="w-full rounded-md border border-[#E5E7EB] bg-white py-1 pl-7 pr-2 text-xs shadow-sm focus:border-[#1B3A5C] focus:outline-none"
      />
    </div>
  )
}

export function FilterBar({ value, options, onChange }: Props) {
  const teams = (options?.teams ?? []).filter((t) => !value.unit || t.unit === value.unit)

  const onUnit = (u: string) => {
    const unit = (u || "") as AugieFunnelUnit | ""
    const keepTeam =
      !value.team || !unit || teams.some((t) => t.team === value.team && t.unit === unit)
    onChange({ unit, ...(keepTeam ? {} : { team: "" }) })
  }

  return (
    <div className="space-y-2 rounded-xl border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Toggle options={RANGES} value={value.range} onChange={(range) => onChange({ range })} />
        {value.range === "custom" ? (
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={value.startDate}
              min={options?.data_floor}
              onChange={(e) => onChange({ startDate: e.target.value })}
              className={SELECT_CLS}
            />
            <span className="text-xs text-[#9CA3AF]">to</span>
            <input
              type="date"
              value={value.endDate}
              min={options?.data_floor}
              onChange={(e) => onChange({ endDate: e.target.value })}
              className={SELECT_CLS}
            />
          </div>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={value.unit}
          onChange={(e) => onUnit(e.target.value)}
          className={SELECT_CLS}
          aria-label="Unit"
        >
          <option value="">All units</option>
          {(options?.units ?? ["CORP", "DFW"]).map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
        <select
          value={value.team}
          onChange={(e) => onChange({ team: e.target.value })}
          className={SELECT_CLS}
          aria-label="Team"
        >
          <option value="">All teams</option>
          {teams.map((t) => (
            <option key={`${t.unit}|${t.team}`} value={t.team}>
              {value.unit ? t.team : `${t.unit} · ${t.team}`}
            </option>
          ))}
        </select>
        <MultiSelectChips
          label="Customer"
          options={options?.customers ?? []}
          selected={value.customer}
          onChange={(customer) => onChange({ customer })}
          width={180}
        />
        <MultiSelectChips
          label="Carrier"
          options={options?.carriers ?? []}
          selected={value.carrier}
          onChange={(carrier) => onChange({ carrier })}
          width={180}
        />
        <SearchBox value={value.q} onCommit={(q) => onChange({ q })} />
      </div>
    </div>
  )
}
