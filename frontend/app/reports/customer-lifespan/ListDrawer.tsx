"use client"

import type { ReactNode } from "react"
import { X } from "lucide-react"
import { fmtInt } from "@/lib/customer-lifespan-api"
import { ErrorBox, Loading } from "./ui"

export interface ListRow {
  id: string
  name: string
  detail: ReactNode
  right: ReactNode
}

export interface ListSection {
  key: string
  label: string
  color: string
  rows: ListRow[]
}

/** The side panel behind a chart: who is inside what you just clicked. */
export function ListDrawer({ title, subtitle, sections, loading, error, onClose, onOpen }: {
  title: string
  subtitle?: string
  sections: ListSection[]
  loading?: boolean
  error?: unknown
  onClose: () => void
  onOpen: (id: string) => void
}) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={onClose}>
      <aside className="h-full w-full max-w-md overflow-y-auto bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-[#1B3A5C]">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-[#6B7280]">{subtitle}</p>}
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-[#6B7280] hover:bg-[#F3F4F6]">
            <X className="h-4 w-4" />
          </button>
        </div>
        {error ? <ErrorBox error={error} /> : null}
        {loading && !error ? <Loading /> : null}
        {!loading && !error && sections.map((s) => (
          <section key={s.key} className="mb-4">
            <h3 className="mb-1 flex items-center gap-2 border-b border-[#F3F4F6] pb-1 text-xs font-semibold" style={{ color: s.color }}>
              {s.label}
              <span className="font-normal text-[#6B7280]">{fmtInt(s.rows.length)}</span>
            </h3>
            {s.rows.length === 0 && <p className="py-1 text-xs text-[#9CA3AF]">None.</p>}
            {s.rows.map((r, i) => (
              <button
                key={`${r.id}-${i}`}
                onClick={() => onOpen(r.id)}
                className="flex w-full items-center justify-between gap-3 rounded px-1 py-1.5 text-left hover:bg-[#F9FAFB]"
              >
                <span className="min-w-0">
                  <span className="block truncate text-xs font-medium text-[#111827]" title={r.name}>{r.name}</span>
                  <span className="block text-[10px] text-[#6B7280]">{r.detail}</span>
                </span>
                <span className="shrink-0 text-[11px]">{r.right}</span>
              </button>
            ))}
          </section>
        ))}
      </aside>
    </div>
  )
}
