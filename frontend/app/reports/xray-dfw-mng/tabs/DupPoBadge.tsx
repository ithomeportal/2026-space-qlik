"use client"

import { Link2 } from "lucide-react"
import { fmtUsd, type XrayDfwMergedOrder } from "@/lib/xray-dfw-api"

/**
 * The "two orders share this PO" marker (Bruno PDF 2026-11-02, GM R1 note).
 * The row's money is already the group's sum; the tooltip lists each member's
 * own amounts so the merge is auditable without leaving the table.
 */
export function DupPoBadge({
  count,
  members,
}: {
  count: number
  members?: XrayDfwMergedOrder[] | null
}) {
  const lines = [...(members ?? [])]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map(
      (m) =>
        `${m.id} · BOL ${m.bol ?? "—"} · ${fmtUsd(m.revenue ?? 0)} / ${fmtUsd(m.profit ?? 0)}`,
    )
  const title = [`${count} orders share this PO — $ shown are their sum:`, ...lines].join("\n")
  return (
    <span
      title={title}
      aria-label={title}
      className="ml-1 inline-flex items-center gap-0.5 rounded bg-[#DBEAFE] px-1 py-0.5 align-middle text-[10px] font-semibold text-[#1D4ED8]"
    >
      <Link2 className="h-3 w-3" aria-hidden />
      {count}
    </span>
  )
}
