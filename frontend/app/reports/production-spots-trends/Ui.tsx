"use client"

import { Loader2 } from "lucide-react"
import type { ReactNode } from "react"
import {
  DASH,
  TONE_CLASS,
  deltaTone,
  fmtDeltaCount,
  fmtDeltaPct,
  type SpotsDelta,
} from "@/lib/production-spots-trends-api"

/** The shared chrome for every panel on this page. Kept in one file so the
 *  loading / error / empty / degraded states are identical everywhere — three
 *  panels that disagree about what "no data" looks like is how a dead feed
 *  gets read as a quiet day. */

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
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold text-[#1B3A5C]">{title}</h2>
          {subtitle ? (
            <span className="text-[10px] text-[#9CA3AF]">{subtitle}</span>
          ) : null}
        </div>
        {right}
      </div>
      {children}
    </div>
  )
}

export function ErrorBlock({ what, error }: { what: string; error: unknown }) {
  return (
    <div className="rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-xs text-[#991B1B]">
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

export function EmptyBlock({ h = 160, msg = "No spot activity in this window." }) {
  return (
    <div
      className="flex items-center justify-center text-xs text-[#6B7280]"
      style={{ height: h }}
    >
      {msg}
    </div>
  )
}

export function Note({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2 text-[11px] text-[#92400E]">
      {children}
    </div>
  )
}

export function Footnote({ children }: { children: ReactNode }) {
  return <div className="mt-2 text-[10px] leading-relaxed text-[#6B7280]">{children}</div>
}

export type CardTone = "default" | "good" | "warn" | "bad"

const TONE_TEXT: Record<CardTone, string> = {
  default: "text-[#1B3A5C]",
  good: "text-[#047857]",
  warn: "text-[#B45309]",
  bad: "text-[#B91C1C]",
}

export function Card({
  label,
  value,
  sub,
  title,
  tone = "default",
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  /** The caveat prose. This codebase documents a metric on the metric. */
  title?: string
  tone?: CardTone
}) {
  return (
    <div
      className="rounded-xl border border-[#E5E7EB] bg-white p-3 shadow-sm"
      title={title}
    >
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className={`mt-1 text-xl font-semibold ${TONE_TEXT[tone]}`}>{value}</div>
      {/* Always render the slot so the cards keep a uniform height. */}
      <div className="mt-0.5 h-4 text-[10px] text-[#9CA3AF]">{sub ?? ""}</div>
    </div>
  )
}

/** A signed change, coloured by whether it is GOOD — not by whether it is up.
 *  `goodDown` inverts it for skip rate, no-reply rate and the like. */
export function DeltaChip({
  delta,
  goodDown = false,
  asPct = false,
}: {
  delta: SpotsDelta | undefined
  goodDown?: boolean
  asPct?: boolean
}) {
  if (!delta || (delta.abs === null && delta.pct === null)) {
    return <span className="text-[10px] text-[#9CA3AF]">{DASH}</span>
  }
  // A rate's own change reads as points, not as a percentage of a percentage.
  const headline = asPct ? fmtDeltaPct(delta.abs) : fmtDeltaCount(delta.abs)
  const tone = deltaTone(delta.abs, goodDown)
  return (
    <span className={`text-[10px] font-semibold ${TONE_CLASS[tone]}`}>
      {headline}
      {!asPct && delta.pct !== null ? (
        <span className="ml-1 font-normal opacity-80">
          ({fmtDeltaPct(delta.pct, 0)})
        </span>
      ) : null}
    </span>
  )
}

export const TH =
  "whitespace-nowrap px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide"
export const TD = "whitespace-nowrap px-2 py-1 text-right tabular-nums"
