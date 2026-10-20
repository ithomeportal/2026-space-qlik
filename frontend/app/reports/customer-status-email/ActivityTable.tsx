import { Fragment, useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import type { ActivityRow } from "@/lib/customer-status-email-api"
import { StatusBadge, fmtCst } from "./StatusBadge"

const BUCKETS = [
  { k: "in_progress", label: "In progress" },
  { k: "scheduled", label: "Scheduled" },
  { k: "delivered", label: "Delivered 24h" },
] as const

function Recipients({ row }: { row: ActivityRow }) {
  const r = row.recipients
  if (!r) return <span className="text-slate-400">—</span>
  return (
    <div className="space-y-0.5 text-xs text-slate-600">
      <div><span className="text-slate-400">To </span>{r.to.join(", ")}</div>
      {r.cc.length > 0 && <div><span className="text-slate-400">CC </span>{r.cc.join(", ")}</div>}
    </div>
  )
}

function LoadsDetail({ row }: { row: ActivityRow }) {
  return (
    <div className="grid gap-3 bg-slate-50 px-4 py-3 text-xs md:grid-cols-4">
      {BUCKETS.map((b) => (
        <div key={b.k}>
          <div className="mb-1 font-semibold text-slate-700">{b.label}</div>
          <div className="text-slate-600">{row.loads?.[b.k]?.join(", ") || "—"}</div>
        </div>
      ))}
      <div>
        <div className="mb-1 font-semibold text-slate-700">From / BCC</div>
        <div className="text-slate-600">{row.recipients?.from ?? "—"}</div>
        <div className="text-slate-600">{row.recipients?.bcc.join(", ") || "—"}</div>
        {row.error && <div className="mt-2 text-red-700">Error: {row.error}</div>}
      </div>
    </div>
  )
}

export function ActivityTable({ rows }: { rows: ActivityRow[] }) {
  const [open, setOpen] = useState<string | null>(null)
  if (rows.length === 0) {
    return <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">No e-mails in this window.</div>
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2" />
            <th className="px-3 py-2">Sent (CST)</th>
            <th className="px-3 py-2">E-mail</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Mode</th>
            <th className="px-3 py-2">Recipients</th>
            {BUCKETS.map((b) => <th key={b.k} className="px-3 py-2 text-right">{b.label}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => {
            const id = `${row.report_key}|${row.slot_key}`
            const isOpen = open === id
            return (
              <Fragment key={id}>
                <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(isOpen ? null : id)}>
                  <td className="px-3 py-2 text-slate-400">
                    {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">{fmtCst(row.finished_at ?? row.claimed_at)}</td>
                  <td className="px-3 py-2">
                    <div className="font-medium text-slate-900">{row.subject ?? row.report_key}</div>
                    <div className="text-xs text-slate-400">slot {row.slot_key}</div>
                  </td>
                  <td className="px-3 py-2"><StatusBadge status={row.status} /></td>
                  <td className="px-3 py-2 text-xs uppercase text-slate-600">{row.mode}</td>
                  <td className="px-3 py-2"><Recipients row={row} /></td>
                  {BUCKETS.map((b) => (
                    <td key={b.k} className="px-3 py-2 text-right tabular-nums">{row.counts?.[b.k] ?? "—"}</td>
                  ))}
                </tr>
                {isOpen && (
                  <tr><td colSpan={9} className="p-0"><LoadsDetail row={row} /></td></tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
