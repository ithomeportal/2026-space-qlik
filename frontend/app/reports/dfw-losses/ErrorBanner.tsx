"use client"

import { AlertTriangle } from "lucide-react"

interface Props {
  errors: unknown[]
  label?: string
}

function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message
  if (typeof e === "string") return e
  return "Unknown error"
}

export function DfwLossesErrorBanner({ errors, label }: Props) {
  const active = errors.filter((e): e is unknown => Boolean(e))
  if (active.length === 0) return null
  const msg = errorMessage(active[0])
  return (
    <div className="flex items-start gap-2 rounded-lg border border-[#FCA5A5] bg-[#FEE2E2] px-3 py-2 text-xs text-[#991B1B]">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="flex-1">
        <div className="font-semibold">
          {label ? `${label} — ` : ""}
          {active.length === 1 ? "A query failed" : `${active.length} queries failed`}
        </div>
        <div className="mt-0.5 font-mono text-[10px] text-[#7F1D1D]">{msg}</div>
        <button
          onClick={() => window.location.reload()}
          className="mt-1 rounded border border-[#FCA5A5] bg-white px-2 py-0.5 text-[10px] font-semibold text-[#991B1B] hover:bg-[#FEF2F2]"
        >
          Reload
        </button>
      </div>
    </div>
  )
}
