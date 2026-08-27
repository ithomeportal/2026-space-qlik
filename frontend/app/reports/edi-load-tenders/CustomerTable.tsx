"use client"

import { useMemo, useState } from "react"
import type { EdiCustomerRow } from "@/lib/edi-load-tenders-api"

const nf = new Intl.NumberFormat("en-US")

type SortKey =
  | "customer"
  | "shipments"
  | "created"
  | "never_created"
  | "cust_cancelled"
  | "cancel_not_actioned"
  | "create_rate"
  | "cancel_rate"

const COLUMNS: { key: SortKey; label: string; numeric: boolean }[] = [
  { key: "customer", label: "Customer", numeric: false },
  { key: "shipments", label: "Shipments", numeric: true },
  { key: "created", label: "Created", numeric: true },
  { key: "create_rate", label: "Create %", numeric: true },
  { key: "never_created", label: "Never created", numeric: true },
  { key: "cust_cancelled", label: "Cust. cancelled", numeric: true },
  { key: "cancel_rate", label: "Cancel %", numeric: true },
  { key: "cancel_not_actioned", label: "Not actioned", numeric: true },
]

function pct(v: number | null) {
  return v === null ? "—" : `${v.toFixed(1)}%`
}

export function CustomerTable({
  rows,
  loading,
}: {
  rows: EdiCustomerRow[]
  loading: boolean
}) {
  const [sort, setSort] = useState<SortKey>("shipments")
  const [asc, setAsc] = useState(false)

  const sorted = useMemo(() => {
    const copy = rows.slice()
    copy.sort((a, b) => {
      const av = a[sort]
      const bv = b[sort]
      if (typeof av === "string" || typeof bv === "string") {
        return String(av).localeCompare(String(bv)) * (asc ? 1 : -1)
      }
      return ((av ?? 0) - (bv ?? 0)) * (asc ? 1 : -1)
    })
    return copy
  }, [rows, sort, asc])

  function toggle(key: SortKey) {
    if (key === sort) {
      setAsc((v) => !v)
    } else {
      setSort(key)
      // Text sorts read best A→Z; counts read best biggest-first.
      setAsc(key === "customer")
    }
  }

  const totals = useMemo(
    () =>
      rows.reduce(
        (acc, r) => ({
          shipments: acc.shipments + r.shipments,
          created: acc.created + r.created,
          never_created: acc.never_created + r.never_created,
          cust_cancelled: acc.cust_cancelled + r.cust_cancelled,
          cancel_not_actioned: acc.cancel_not_actioned + r.cancel_not_actioned,
        }),
        {
          shipments: 0,
          created: 0,
          never_created: 0,
          cust_cancelled: 0,
          cancel_not_actioned: 0,
        },
      ),
    [rows],
  )

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <header className="border-b border-slate-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-900">By trading partner</h2>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  onClick={() => toggle(c.key)}
                  className={`cursor-pointer select-none px-3 py-2 font-medium hover:text-slate-800 ${
                    c.numeric ? "text-right" : "text-left"
                  }`}
                >
                  {c.label}
                  {sort === c.key ? (asc ? " ▲" : " ▼") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && rows.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length} className="px-3 py-8 text-center text-slate-400">
                  Loading…
                </td>
              </tr>
            ) : (
              sorted.map((r) => (
                <tr key={r.customer_id} className="hover:bg-slate-50">
                  <td className="px-3 py-2">{r.customer}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {nf.format(r.shipments)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {nf.format(r.created)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{pct(r.create_rate)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-amber-700">
                    {nf.format(r.never_created)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {nf.format(r.cust_cancelled)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{pct(r.cancel_rate)}</td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums ${
                      r.cancel_not_actioned > 0 ? "font-medium text-red-700" : ""
                    }`}
                  >
                    {nf.format(r.cancel_not_actioned)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
          {rows.length > 0 ? (
            <tfoot className="border-t-2 border-slate-200 bg-slate-50 font-medium">
              <tr>
                <td className="px-3 py-2">Total</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {nf.format(totals.shipments)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {nf.format(totals.created)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {totals.shipments
                    ? `${((100 * totals.created) / totals.shipments).toFixed(1)}%`
                    : "—"}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {nf.format(totals.never_created)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {nf.format(totals.cust_cancelled)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {totals.shipments
                    ? `${((100 * totals.cust_cancelled) / totals.shipments).toFixed(1)}%`
                    : "—"}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-red-700">
                  {nf.format(totals.cancel_not_actioned)}
                </td>
              </tr>
            </tfoot>
          ) : null}
        </table>
      </div>
    </section>
  )
}
