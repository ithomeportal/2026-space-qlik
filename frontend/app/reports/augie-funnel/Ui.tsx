"use client"

import { Loader2 } from "lucide-react"
import type { ReactNode } from "react"

/** Shared panel chrome so loading / error / empty read identically everywhere —
 *  a dead feed must never look like a quiet day. */

export function Panel({
  title,
  subtitle,
  right,
  children,
}: {
  title: string
  subtitle?: ReactNode
  right?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-[#1B3A5C]">{title}</h2>
          {subtitle ? <p className="mt-0.5 text-[11px] text-[#6B7280]">{subtitle}</p> : null}
        </div>
        {right}
      </div>
      {children}
    </section>
  )
}

export function ErrorBlock({ what, error }: { what: string; error: unknown }) {
  return (
    <div className="rounded-lg border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-xs text-[#991B1B]">
      Could not load {what}: {error instanceof Error ? error.message : "unknown error"}
    </div>
  )
}

export function LoadingBlock({ h = 160 }: { h?: number }) {
  return (
    <div className="flex items-center justify-center" style={{ height: h }}>
      <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
    </div>
  )
}

export function EmptyBlock({ h = 120, msg }: { h?: number; msg: string }) {
  return (
    <div
      className="flex items-center justify-center text-xs text-[#6B7280]"
      style={{ height: h }}
    >
      {msg}
    </div>
  )
}

export function Toggle<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { k: T; label: string }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div className="inline-flex flex-wrap gap-1 rounded-md border border-[#E5E7EB] bg-white p-0.5">
      {options.map((o) => (
        <button
          key={o.k}
          type="button"
          onClick={() => onChange(o.k)}
          className={`rounded px-2.5 py-1 text-xs ${
            value === o.k ? "bg-[#1B3A5C] text-white" : "text-[#4B5563] hover:bg-[#F3F4F6]"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
