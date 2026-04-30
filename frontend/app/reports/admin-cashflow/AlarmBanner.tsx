"use client"

import { AlertTriangle } from "lucide-react"
import { fmtUsd } from "./format"

interface Props {
  total: number
  threshold: number
}

export function AlarmBanner({ total, threshold }: Props) {
  return (
    <div
      className="flex items-start gap-3 rounded-xl border border-[#FCA5A5] bg-[#FEF2F2] px-4 py-3 shadow-sm"
      role="alert"
    >
      <AlertTriangle className="mt-0.5 h-5 w-5 text-[#B91C1C]" />
      <div className="flex-1">
        <div className="text-sm font-semibold text-[#991B1B]">
          Cash parked unbilled has crossed the {fmtUsd(threshold)} threshold
        </div>
        <div className="mt-0.5 text-xs text-[#7F1D1D]">
          Delivered-but-not-billed plus ready-but-not-billed totals{" "}
          <span className="font-semibold tabular-nums">{fmtUsd(total)}</span>{" "}
          for the current filters. Review the unbilled tables below to push
          billing through.
        </div>
      </div>
    </div>
  )
}
