"use client"

import type { ReactNode } from "react"

/**
 * Numbered section header — "02 · ANNUAL MOVEMENT" over a serif display title.
 *
 * The numbering comes from the request (which specifies 02, 03 and 05, and
 * skips 04); it is a new convention for this app, so it lives here rather than
 * in a shared component until a second report wants it. The eyebrow keeps the
 * existing site-wide uppercase/tracking treatment.
 */
export function Section({
  index,
  eyebrow,
  title,
  subtitle,
  actions,
  children,
}: {
  index: string
  eyebrow: string
  title: string
  subtitle?: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="rounded-2xl border border-[#E5E7EB] bg-white p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#0F766E]">
            <span className="tabular-nums">{index}</span>
            <span className="mx-1.5 text-[#9CA3AF]">·</span>
            {eyebrow}
          </div>
          <h2 className="mt-1 font-serif text-2xl font-semibold text-[#111827]">{title}</h2>
          {subtitle ? (
            <p className="mt-0.5 text-xs text-[#6B7280]">{subtitle}</p>
          ) : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </section>
  )
}

/** Segmented toggle, matching the site's existing filter-bar treatment. */
export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: { k: T; label: string }[]
  value: T
  onChange: (next: T) => void
  label?: string
}) {
  return (
    <div className="flex flex-col items-end gap-1">
      {label ? (
        <span className="text-[10px] font-semibold uppercase tracking-wider text-[#9CA3AF]">
          {label}
        </span>
      ) : null}
      <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
        {options.map((opt) => (
          <button
            key={String(opt.k)}
            type="button"
            onClick={() => onChange(opt.k)}
            aria-pressed={value === opt.k}
            className={`px-3 py-1.5 transition-colors ${
              value === opt.k
                ? "rounded-lg bg-[#1B3A5C] font-semibold text-white shadow-sm"
                : "text-[#6B7280] hover:text-[#111827]"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}
