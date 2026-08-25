"use client"

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-08-24 "Aging Updates") R2 — the "Table" pop-up behind the
// "Top customers contributing to delays" card.
//
// Thirteen columns: Customer, then Late / Revenue / AVG Days across four
// DISCRETE months (this month, last month, two and three months back). The
// card behind it is one number per customer for the page's date range; this is
// the same customers read as a trend.
//
// The months are NOT derived here. `meta.buckets` names the month each of
// tm/lm/l2m/l3m stands for, so the header cannot drift from the numbers when
// the pop-up is left open across midnight on the 1st.
//
// Overlay is `UnbilledExpandModal` — a plain fixed div, React-18 safe, the
// same idiom every other pop-up in this report uses.
// ---------------------------------------------------------------------------

import { Loader2 } from "lucide-react"

import { SortableTh, useSortable } from "@/components/SortableTable"
import {
  useTopDelayedCustomersMonthly,
  type AdminCashflowFilters,
  type TopDelayedBucket,
  type TopDelayedBucketKey,
  type TopDelayedMonthlyRow,
} from "@/lib/admin-cashflow-api"

import { fmtCount, fmtNum1, fmtUsd } from "./format"
import { UnbilledExpandModal } from "./UnbilledShared"

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

/**
 * "2026-08-01" → "Aug 2026", parsed by hand.
 *
 * `new Date("2026-08-01")` is UTC midnight, which renders as the PREVIOUS
 * month for anyone west of Greenwich — the column would read "Jul" while its
 * numbers are August's.
 */
function monthLabel(iso: string | undefined): string {
  if (!iso) return ""
  const [y, m] = iso.split("-")
  const idx = Number(m) - 1
  return idx >= 0 && idx < 12 ? `${MONTHS[idx]} ${y}` : iso
}

const KEYS: TopDelayedBucketKey[] = ["tm", "lm", "l2m", "l3m"]
const SHORT: Record<TopDelayedBucketKey, string> = {
  tm: "TM",
  lm: "LM",
  l2m: "L2M",
  l3m: "L3M",
}

export function TopDelayedMonthlyModal({
  filters,
  onClose,
}: {
  filters: AdminCashflowFilters
  onClose: () => void
}) {
  const { data, isLoading } = useTopDelayedCustomersMonthly(filters, true)

  const rows = (data?.data ?? []) as TopDelayedMonthlyRow[]
  const buckets = (data?.meta?.buckets ?? []) as TopDelayedBucket[]
  const labelFor = (k: TopDelayedBucketKey) =>
    monthLabel(buckets.find((b) => b.key === k)?.month)

  // Money and counts lead with the biggest first; only the name starts ascending.
  const { sorted, ...sortState } = useSortable<TopDelayedMonthlyRow>(
    rows,
    "late_revenue_total",
    "desc",
    (key) => (key === "customer_name" ? "asc" : "desc"),
  )

  const total = data?.meta?.total ?? rows.length
  const truncated = data?.meta?.truncated === true

  return (
    <UnbilledExpandModal
      title="Top customers contributing to delays — by month"
      subtitle={
        buckets.length
          ? `Late = bill_date − dest_actual_departure > ${data?.meta?.late_days ?? 2} days · ` +
            `customers averaging ≥ ${data?.meta?.min_avg_days ?? 2} days · ` +
            KEYS.map((k) => `${SHORT[k]} = ${labelFor(k)}`).join(" · ")
          : "Late = bill_date − dest_actual_departure > 2 days"
      }
      onClose={onClose}
      wide
    >
      {isLoading ? (
        <div className="flex h-40 items-center justify-center text-[#6B7280]">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : rows.length === 0 ? (
        <div className="py-12 text-center text-xs text-[#9CA3AF]">
          No customers with delays in the last four months for these filters
        </div>
      ) : (
        <>
          <div className="overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[10px] uppercase tracking-wider text-[#6B7280]">
                <tr className="border-b border-[#E5E7EB]">
                  <SortableTh label="Customer" columnKey="customer_name" state={sortState} />
                  {KEYS.map((k) => (
                    <SortableTh
                      key={`late_${k}`}
                      label={`Late ${SHORT[k]}`}
                      columnKey={`late_${k}`}
                      state={sortState}
                      align="right"
                      className={k === "tm" ? "border-l border-[#E5E7EB]" : ""}
                    />
                  ))}
                  {KEYS.map((k) => (
                    <SortableTh
                      key={`rev_${k}`}
                      label={`Rev ${SHORT[k]}`}
                      columnKey={`rev_${k}`}
                      state={sortState}
                      align="right"
                      className={k === "tm" ? "border-l border-[#E5E7EB]" : ""}
                    />
                  ))}
                  {KEYS.map((k) => (
                    <SortableTh
                      key={`avg_days_${k}`}
                      label={`AVG Days ${SHORT[k]}`}
                      columnKey={`avg_days_${k}`}
                      state={sortState}
                      align="right"
                      className={k === "tm" ? "border-l border-[#E5E7EB]" : ""}
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => (
                  <tr key={r.customer_name} className="border-b border-[#F3F4F6] last:border-0">
                    <td className="max-w-[280px] truncate px-3 py-1.5" title={r.customer_name}>
                      {r.customer_name}
                    </td>
                    {KEYS.map((k) => (
                      <td
                        key={`late_${k}`}
                        className={`px-3 py-1.5 text-right tabular-nums ${
                          k === "tm" ? "border-l border-[#F3F4F6]" : ""
                        }`}
                      >
                        {fmtCount(r[`late_${k}`] as number | null)}
                      </td>
                    ))}
                    {KEYS.map((k) => (
                      <td
                        key={`rev_${k}`}
                        className={`px-3 py-1.5 text-right font-semibold tabular-nums text-[#991B1B] ${
                          k === "tm" ? "border-l border-[#F3F4F6]" : ""
                        }`}
                      >
                        {fmtUsd(r[`rev_${k}`] as number | null)}
                      </td>
                    ))}
                    {KEYS.map((k) => (
                      <td
                        key={`avg_days_${k}`}
                        className={`px-3 py-1.5 text-right tabular-nums ${
                          k === "tm" ? "border-l border-[#F3F4F6]" : ""
                        }`}
                      >
                        {fmtNum1(r[`avg_days_${k}`] as number | null)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* A worklist that drops rows must say so. */}
          <div className="border-t border-[#E5E7EB] px-3 py-2 text-[10px] text-[#6B7280]">
            {truncated
              ? `Showing ${sorted.length} of ${total} customers (largest $ at risk first)`
              : `${total} customer${total === 1 ? "" : "s"}`}
          </div>
        </>
      )}
    </UnbilledExpandModal>
  )
}
