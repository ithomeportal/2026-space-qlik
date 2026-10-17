"use client"

import { ArrowDown, ArrowRight, CornerDownRight } from "lucide-react"
import type { ReactNode } from "react"
import {
  AUGIE_REASONS,
  REASON_HELP,
  REASON_LABELS,
  fmtInt,
  fmtPct,
  type AugieFunnelNode,
  type AugieFunnelSummary,
} from "@/lib/augie-funnel-api"

interface Props {
  data: AugieFunnelSummary
  node: AugieFunnelNode
  onNode: (n: AugieFunnelNode) => void
}

function Box({
  active,
  onClick,
  tone,
  title,
  value,
  pct,
  children,
}: {
  active: boolean
  onClick: () => void
  tone: string
  title: string
  value: number
  pct?: ReactNode
  children?: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`w-full rounded-xl border-2 bg-white px-4 py-3 text-left shadow-sm transition hover:shadow-md ${
        active ? "border-[#1B3A5C] ring-2 ring-[#1B3A5C]/20" : "border-[#E5E7EB]"
      }`}
    >
      <div className={`text-[11px] font-semibold uppercase tracking-wider ${tone}`}>{title}</div>
      <div className="mt-1 text-2xl font-bold text-[#111827]">{fmtInt(value)}</div>
      {pct ? <div className="text-xs text-[#4B5563]">{pct}</div> : null}
      {children}
    </button>
  )
}

function Arrow() {
  return (
    <div className="flex shrink-0 items-center justify-center text-[#9CA3AF]">
      <ArrowRight className="hidden h-5 w-5 lg:block" />
      <ArrowDown className="h-5 w-5 lg:hidden" />
    </div>
  )
}

function NotInAugie({ data, node, onNode }: Props) {
  const active = node === "not_tracked"
  return (
    <div
      className={`rounded-xl border-2 bg-white shadow-sm ${
        active ? "border-[#1B3A5C] ring-2 ring-[#1B3A5C]/20" : "border-[#FCA5A5]"
      }`}
    >
      <button
        type="button"
        onClick={() => onNode("not_tracked")}
        aria-pressed={active}
        className="w-full rounded-t-xl px-4 py-3 text-left hover:bg-[#FEF2F2]"
      >
        <div className="text-[11px] font-semibold uppercase tracking-wider text-[#B91C1C]">
          Not in Augie
        </div>
        <div className="mt-1 text-2xl font-bold text-[#111827]">{fmtInt(data.not_tracked)}</div>
        <div className="text-xs text-[#4B5563]">{fmtPct(data.not_tracked_pct)} of pickups</div>
      </button>
      <ul className="divide-y divide-[#F3F4F6] border-t border-[#F3F4F6]">
        {AUGIE_REASONS.map((r) => {
          const on = node === r
          return (
            <li key={r}>
              <button
                type="button"
                onClick={() => onNode(r)}
                aria-pressed={on}
                className={`flex w-full items-start gap-3 px-4 py-2 text-left text-xs hover:bg-[#F9FAFB] ${
                  on ? "bg-[#EFF6FF]" : ""
                }`}
              >
                <span className="min-w-0 flex-1">
                  <span className={`font-semibold ${on ? "text-[#1B3A5C]" : "text-[#111827]"}`}>
                    {REASON_LABELS[r]}
                  </span>
                  <span className="block text-[11px] text-[#6B7280]">{REASON_HELP[r]}</span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="block font-semibold text-[#111827]">{fmtInt(data[r])}</span>
                  <span className="block text-[11px] text-[#6B7280]">
                    {fmtPct(data.reason_pct?.[r])}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** Bruno's sketch: Pickups → Tracked → Contacted → Info captured, with the
 *  untracked branch hanging under Pickups. Every box / reason sets the detail
 *  table's `node`. */
export function FunnelFlow({ data, node, onNode }: Props) {
  return (
    <div className="space-y-3">
      <div className="flex flex-col items-stretch gap-2 lg:flex-row">
        <div className="lg:w-1/4">
          <Box
            active={node === "all"}
            onClick={() => onNode("all")}
            tone="text-[#1B3A5C]"
            title="Pickups"
            value={data.pickups}
            pct="every load picked up in the window"
          />
        </div>
        <Arrow />
        <div className="lg:w-1/4">
          <Box
            active={node === "tracked"}
            onClick={() => onNode("tracked")}
            tone="text-[#1D4ED8]"
            title="Tracked by Augie"
            value={data.tracked}
            pct={`${fmtPct(data.tracked_pct)} of pickups`}
          >
            <div className="mt-1 text-[11px] text-[#9CA3AF]">
              {fmtInt(data.has_status)} carry an Augie status in the app
            </div>
          </Box>
        </div>
        <Arrow />
        <div className="lg:w-1/4">
          <Box
            active={node === "contacted"}
            onClick={() => onNode("contacted")}
            tone="text-[#7C3AED]"
            title="Contacted"
            value={data.contacted}
            pct={`${fmtPct(data.contacted_pct)} of tracked`}
          >
            <div className="mt-1 text-[11px] text-[#9CA3AF]">
              {fmtInt(data.tracked - data.contacted)} tracked loads never got a call or
              update back
            </div>
          </Box>
        </div>
        <Arrow />
        <div className="lg:w-1/4">
          <Box
            active={node === "captured"}
            onClick={() => onNode("captured")}
            tone="text-[#047857]"
            title="Info captured"
            value={data.captured}
            pct={`${fmtPct(data.captured_pct)} of tracked`}
          />
        </div>
      </div>

      <div className="flex items-start gap-2 lg:w-1/2">
        <CornerDownRight className="mt-3 h-5 w-5 shrink-0 text-[#FCA5A5]" />
        <div className="min-w-0 flex-1">
          <NotInAugie data={data} node={node} onNode={onNode} />
        </div>
      </div>
    </div>
  )
}
