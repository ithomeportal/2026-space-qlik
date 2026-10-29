"use client"

import type { ReactNode } from "react"
import { Loader2 } from "lucide-react"
import { STATUS_META, type Status } from "@/lib/customer-lifespan-api"

export function Card({ title, hint, right, children }: {
  title?: string
  hint?: string
  right?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      {(title || right) && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            {title && <h2 className="text-sm font-semibold text-[#1B3A5C]">{title}</h2>}
            {hint && <p className="mt-0.5 max-w-3xl text-[11px] text-[#6B7280]">{hint}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  )
}

export function Loading({ height = "h-48" }: { height?: string }) {
  return (
    <div className={`flex ${height} items-center justify-center text-[#6B7280]`}>
      <Loader2 className="h-5 w-5 animate-spin" />
    </div>
  )
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : "Could not load this section"
  return (
    <div className="rounded-lg border border-[#FECACA] bg-[#FEF2F2] p-3 text-xs text-[#991B1B]">{msg}</div>
  )
}

export function StatusChip({ status }: { status: Status }) {
  const m = STATUS_META[status]
  return <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ${m.chip}`}>{m.label}</span>
}

/** Segmented control — the same look as the report tabs. */
export function Segmented<T extends string | number>({ value, options, onChange, label }: {
  value: T
  options: readonly { k: T; label: string }[]
  onChange: (v: T) => void
  label?: string
}) {
  return (
    <div className="flex items-center gap-2 text-xs">
      {label && <span className="text-[#6B7280]">{label}</span>}
      <div className="flex rounded-lg border border-[#E5E7EB] bg-white">
        {options.map((o) => (
          <button
            key={String(o.k)}
            onClick={() => onChange(o.k)}
            className={`px-3 py-1.5 first:rounded-l-lg last:rounded-r-lg ${
              value === o.k ? "bg-[#1B3A5C] font-semibold text-white" : "text-[#6B7280] hover:text-[#111827]"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}

/** 24-month revenue sparkline; months with no load stay on the baseline. */
export function Sparkline({ values, color = "#1B3A5C" }: { values: number[]; color?: string }) {
  const w = 96
  const h = 22
  const max = Math.max(...values, 1)
  const step = w / Math.max(values.length - 1, 1)
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(h - (Math.max(v, 0) / max) * (h - 2) - 1).toFixed(1)}`)
  return (
    <svg width={w} height={h} className="block" aria-hidden>
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth={1.25} />
    </svg>
  )
}
