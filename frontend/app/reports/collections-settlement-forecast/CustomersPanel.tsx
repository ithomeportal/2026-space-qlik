"use client"

import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"
import { SortableTh, useSortable } from "@/components/SortableTable"
import { fmtUsd, useByCustomer, type CustomerRow } from "@/lib/collections-settlement-forecast-api"
import { ErrorBox } from "./ThisWeekPanel"

type FlatRow = CustomerRow & { w0: number; w1: number; w2: number; w3: number; w4: number }

const WEEK_COLS = ["w0", "w1", "w2", "w3", "w4"] as const
const WEEK_LABELS = ["This week", "+1", "+2", "+3", "+4"]

export function CustomersPanel() {
  const { data, isLoading, error } = useByCustomer()
  const [q, setQ] = useState("")
  const rows: FlatRow[] = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (data?.data ?? [])
      .filter((r) => !needle || `${r.customer_id} ${r.customer_name}`.toLowerCase().includes(needle))
      .map((r) => ({ ...r, w0: r.weeks[0], w1: r.weeks[1], w2: r.weeks[2], w3: r.weeks[3], w4: r.weeks[4] }))
  }, [data, q])
  const sort = useSortable<FlatRow>(rows, "expected_5w", "desc")

  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
      </div>
    )
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 text-xs text-[#6B7280]">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search customer…"
          className="w-64 rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
        />
        {/* Every customer is listed — the count is the whole population, not a page. */}
        <span>{rows.length} of {data.meta.total} customers</span>
      </div>
      <div className="max-h-[70vh] overflow-auto rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-[#F9FAFB] text-[#6B7280]">
            <tr>
              <SortableTh label="Customer" columnKey="customer_name" state={sort} />
              <SortableTh label="Avg pay days" columnKey="avg_pay_days" state={sort} align="right" />
              <SortableTh label="Open AR" columnKey="open" state={sort} align="right" />
              <SortableTh label="Past due" columnKey="past_due" state={sort} align="right" />
              {WEEK_COLS.map((k, i) => (
                <SortableTh key={k} label={WEEK_LABELS[i]} columnKey={k} state={sort} align="right" />
              ))}
              <SortableTh label="5-week total" columnKey="expected_5w" state={sort} align="right" />
            </tr>
          </thead>
          <tbody>
            {sort.sorted.map((r) => (
              <tr key={r.customer_id} className="border-t border-[#F3F4F6]">
                <td className="px-3 py-1.5" title={r.customer_id}>{r.customer_name || r.customer_id}</td>
                <td className="px-3 py-1.5 text-right tabular-nums"
                  title={r.pay_days_known === false ? "No McLeod average — Bruce's default 30 days" : undefined}>
                  {r.avg_pay_days ?? "—"}{r.pay_days_known === false ? "*" : ""}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.open)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.past_due)}</td>
                {WEEK_COLS.map((k) => (
                  <td key={k} className="px-3 py-1.5 text-right tabular-nums">{r[k] ? fmtUsd(r[k]) : ""}</td>
                ))}
                <td className="px-3 py-1.5 text-right font-semibold tabular-nums">{fmtUsd(r.expected_5w)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-[#6B7280]">
        Weeks = Bruce&apos;s expected collections: each shipped load&apos;s revenue on its bill date + the
        customer&apos;s McLeod average days to pay (* = no McLeod average, 30 days); weeks whose loads have not
        shipped take the customer&apos;s 3-week run-rate. Open AR and past due are today&apos;s balances.
      </p>
    </div>
  )
}
