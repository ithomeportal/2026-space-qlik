"use client"

import { AlertTriangle } from "lucide-react"
import type { EdiExceptionRow } from "@/lib/edi-load-tenders-api"

const nf = new Intl.NumberFormat("en-US")
const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})

/** McLeod order status → what it means for a cancel that was never actioned. */
const STATUS_LABEL: Record<string, string> = {
  D: "Delivered",
  P: "In progress",
  A: "Pending cover",
  V: "Voided",
}

interface Props {
  rows: EdiExceptionRow[]
  totalCharge: number
  truncated: boolean
  liveOnly: boolean
  onLiveOnlyChange: (next: boolean) => void
  loading: boolean
}

export function ExceptionBoard({
  rows,
  totalCharge,
  truncated,
  liveOnly,
  onLiveOnlyChange,
  loading,
}: Props) {
  return (
    <section className="rounded-lg border border-red-200 bg-white">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-red-100 bg-red-50 px-4 py-3">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
          <div>
            <h2 className="text-sm font-semibold text-red-900">
              Cancelled by the customer — not cancelled here
            </h2>
            <p className="mt-0.5 text-xs text-red-700">
              The customer sent an EDI cancellation, we had already raised the order,
              and nothing cancelled it on our side.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <label className="flex cursor-pointer items-center gap-2 text-xs text-red-900">
            <input
              type="checkbox"
              checked={liveOnly}
              onChange={(e) => onLiveOnlyChange(e.target.checked)}
              className="h-3.5 w-3.5 accent-red-600"
            />
            Still actionable only
          </label>
          <div className="text-right">
            <div className="text-xs uppercase tracking-wide text-red-700">Exposure</div>
            <div className="text-lg font-semibold tabular-nums text-red-900">
              {money.format(totalCharge)}
            </div>
          </div>
        </div>
      </header>

      {/* Wide tables scroll inside their own box, never the document. */}
      <div className="max-h-[420px] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2 font-medium">Order</th>
              <th className="px-3 py-2 font-medium">Shipment</th>
              <th className="px-3 py-2 font-medium">Customer</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Team</th>
              <th className="px-3 py-2 text-right font-medium">Revenue</th>
              <th className="px-3 py-2 font-medium">Cancel received</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-slate-400">
                  Loading…
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-slate-500">
                  Nothing outstanding for this scope.
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={`${r.order_id}-${r.shipment_id}`} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono text-xs">{r.order_id}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-600">
                    {r.shipment_id}
                  </td>
                  <td className="px-3 py-2">{r.customer}</td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        r.status === "V"
                          ? "rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600"
                          : "rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-800"
                      }
                    >
                      {STATUS_LABEL[r.status] ?? r.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{r.team_id ?? "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {money.format(r.total_charge)}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {r.last_received ? r.last_received.slice(0, 16).replace("T", " ") : "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <footer className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
        {nf.format(rows.length)} order{rows.length === 1 ? "" : "s"}
        {truncated ? " — capped, narrow the date range to see the rest" : ""}
        {liveOnly
          ? " · showing only orders still in D/P status"
          : " · including orders already voided in McLeod"}
      </footer>
    </section>
  )
}
