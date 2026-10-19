"use client"

import {
  DASH,
  NODE_LABELS,
  REASON_LABELS,
  fmtInt,
  fmtNaiveStamp,
  type AugieFunnelNode,
  type AugieFunnelSort,
  type AugieLoadRow,
  type AugieLoadsResult,
} from "@/lib/augie-funnel-api"
import { EmptyBlock, ErrorBlock, LoadingBlock, Panel } from "./Ui"

interface Props {
  data: AugieLoadsResult | undefined
  loading: boolean
  error: unknown
  node: AugieFunnelNode
  onClearNode: () => void
  sort: AugieFunnelSort
  onSort: (s: AugieFunnelSort) => void
}

/** Server-side sort: each column maps to one router `_SORTS` token. Pickup is
 *  the only column with both directions. */
const COLUMNS: { label: string; sorts?: AugieFunnelSort[] }[] = [
  { label: "Order", sorts: ["order_asc"] },
  { label: "Pickup (CST)", sorts: ["pickup_desc", "pickup_asc"] },
  { label: "Unit / Team", sorts: ["team_asc"] },
  { label: "Customer", sorts: ["customer_asc"] },
  { label: "Carrier", sorts: ["carrier_asc"] },
  { label: "Origin → Destination" },
  { label: "Augie status" },
  { label: "Stage", sorts: ["stage_asc"] },
]

function stage(r: AugieLoadRow): { text: string; cls: string } {
  if (r.captured) return { text: "Carrier gave an update", cls: "bg-[#D1FAE5] text-[#065F46]" }
  if (r.contacted) return { text: "Carrier contacted", cls: "bg-[#EDE9FE] text-[#5B21B6]" }
  if (r.tracked) return { text: "Sent, no update yet", cls: "bg-[#DBEAFE] text-[#1D4ED8]" }
  const why = r.reason ? REASON_LABELS[r.reason] : "Unknown"
  return { text: `Not sent: ${why}`, cls: "bg-[#FEE2E2] text-[#991B1B]" }
}

function HeaderCell({
  col,
  sort,
  onSort,
}: {
  col: (typeof COLUMNS)[number]
  sort: AugieFunnelSort
  onSort: (s: AugieFunnelSort) => void
}) {
  if (!col.sorts) return <th className="px-3 py-1.5 text-left font-semibold">{col.label}</th>
  const idx = col.sorts.indexOf(sort)
  const active = idx >= 0
  const next = active ? col.sorts[(idx + 1) % col.sorts.length] : col.sorts[0]
  const arrow = active ? (sort.endsWith("_desc") ? "▼" : "▲") : "↕"
  return (
    <th className="px-3 py-1.5 text-left font-semibold">
      <button
        type="button"
        onClick={() => onSort(next)}
        className={`flex items-center gap-1 hover:text-[#111827] ${active ? "text-[#1B3A5C]" : ""}`}
        title="Sort"
      >
        <span>{col.label}</span>
        <span className="text-[9px] leading-none text-[#9CA3AF]">{arrow}</span>
      </button>
    </th>
  )
}

function Row({ r }: { r: AugieLoadRow }) {
  const s = stage(r)
  const unitTeam = [r.unit, r.team].filter(Boolean).join(" / ") || DASH
  return (
    <tr className="hover:bg-[#F9FAFB]">
      <td className="whitespace-nowrap px-3 py-1.5 font-mono">{r.order_id}</td>
      <td className="whitespace-nowrap px-3 py-1.5 tabular-nums">{fmtNaiveStamp(r.pickup_at)}</td>
      <td className="whitespace-nowrap px-3 py-1.5">{unitTeam}</td>
      <td className="max-w-[220px] truncate px-3 py-1.5" title={r.customer ?? ""}>
        {r.customer || DASH}
      </td>
      <td className="max-w-[220px] truncate px-3 py-1.5" title={r.carrier ?? ""}>
        {r.carrier || DASH}
      </td>
      <td className="whitespace-nowrap px-3 py-1.5">
        {r.origin || DASH} → {r.destination || DASH}
      </td>
      <td className="whitespace-nowrap px-3 py-1.5">{r.augie_status || DASH}</td>
      <td className="whitespace-nowrap px-3 py-1.5">
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${s.cls}`}>
          {s.text}
        </span>
      </td>
    </tr>
  )
}

export function LoadsTable({ data, loading, error, node, onClearNode, sort, onSort }: Props) {
  const rows = data?.rows ?? []
  const subtitle = data
    ? `${fmtInt(data.total)} loads${
        data.truncated ? ` · showing first ${fmtInt(rows.length)}` : ""
      }`
    : undefined

  let body
  if (error) body = <ErrorBlock what="the loads" error={error} />
  else if (loading && rows.length === 0) body = <LoadingBlock />
  else if (rows.length === 0) body = <EmptyBlock msg="No loads match this step and these filters." />
  else
    body = (
      <div className="max-h-[640px] overflow-auto">
        <table className="w-full min-w-[1100px] text-xs">
          <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[#6B7280]">
            <tr>
              {COLUMNS.map((c) => (
                <HeaderCell key={c.label} col={c} sort={sort} onSort={onSort} />
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {rows.map((r) => (
              <Row key={`${r.order_id}|${r.pickup_day}`} r={r} />
            ))}
          </tbody>
        </table>
      </div>
    )

  return (
    <Panel
      title={`Loads — ${NODE_LABELS[node]}`}
      subtitle={subtitle}
      right={
        node !== "all" ? (
          <button
            type="button"
            onClick={onClearNode}
            className="rounded-md border border-[#E5E7EB] px-2 py-1 text-xs text-[#4B5563] hover:bg-[#F3F4F6]"
          >
            Show all loads picked up
          </button>
        ) : null
      }
    >
      {data?.truncated ? (
        <p className="mb-2 text-[11px] text-[#92400E]">
          Showing the first {fmtInt(rows.length)} of {fmtInt(data.total)} — narrow the filters
          to see the rest.
        </p>
      ) : null}
      {body}
    </Panel>
  )
}
