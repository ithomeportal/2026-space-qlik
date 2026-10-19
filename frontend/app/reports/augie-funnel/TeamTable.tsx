"use client"

import { useMemo } from "react"
import { SortableTh, useSortable } from "@/components/SortableTable"
import {
  AUGIE_REASONS,
  REASON_LABELS,
  fmtInt,
  fmtPct,
  type AugieTeamRow,
} from "@/lib/augie-funnel-api"
import { EmptyBlock, ErrorBlock, LoadingBlock, Panel } from "./Ui"

interface Props {
  rows: AugieTeamRow[] | undefined
  loading: boolean
  error: unknown
}

type Col = { key: string; label: string; pct?: boolean; align?: "left" | "right" }

const COLS: Col[] = [
  { key: "unit", label: "Unit", align: "left" },
  { key: "team", label: "Team", align: "left" },
  { key: "pickups", label: "Picked up" },
  { key: "tracked", label: "Sent to Augie" },
  { key: "tracked_pct", label: "% sent", pct: true },
  { key: "contacted_pct", label: "Contacted %", pct: true },
  { key: "captured", label: "Updates" },
  { key: "captured_pct", label: "% with update", pct: true },
  { key: "not_tracked", label: "Not sent" },
  ...AUGIE_REASONS.map((r) => ({ key: r, label: REASON_LABELS[r] })),
]

function cell(row: Record<string, unknown>, c: Col) {
  const v = row[c.key]
  if (c.align === "left") return (v as string | null) || "—"
  return c.pct ? fmtPct(v as number | null) : fmtInt(v as number | null)
}

export function TeamTable({ rows, loading, error }: Props) {
  const flat = useMemo(
    () => (rows ?? []).map((r) => ({ ...r }) as unknown as Record<string, unknown>),
    [rows],
  )
  const sort = useSortable(flat, "pickups", "desc")

  let body
  if (error) body = <ErrorBlock what="the team table" error={error} />
  else if (loading && flat.length === 0) body = <LoadingBlock />
  else if (flat.length === 0) body = <EmptyBlock msg="No loads picked up in this window." />
  else
    body = (
      <div className="overflow-x-auto">
        <table className="w-full min-w-[960px] text-xs">
          <thead className="bg-[#F9FAFB] text-[#6B7280]">
            <tr>
              {COLS.map((c) => (
                <SortableTh
                  key={c.key}
                  label={c.label}
                  columnKey={c.key}
                  state={sort}
                  align={c.align ?? "right"}
                />
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {sort.sorted.map((r) => (
              <tr key={`${r.unit ?? ""}|${r.team ?? ""}`} className="hover:bg-[#F9FAFB]">
                {COLS.map((c) => (
                  <td
                    key={c.key}
                    className={`whitespace-nowrap px-3 py-1.5 ${
                      c.align === "left" ? "text-left" : "text-right tabular-nums"
                    }`}
                  >
                    {cell(r, c)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )

  return (
    <Panel
      title="By team"
      subtitle="% sent is of loads picked up; Contacted % and % with update are of loads sent to Augie. — means nothing to divide by."
    >
      {body}
    </Panel>
  )
}
