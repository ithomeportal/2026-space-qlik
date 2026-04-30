"use client"

import { Loader2, Users } from "lucide-react"
import {
  useTopDelayedCustomers,
  type AdminCashflowFilters,
} from "@/lib/admin-cashflow-api"
import { fmtCount, fmtNum1, fmtUsd } from "./format"

interface Props {
  filters: AdminCashflowFilters
}

export function TopDelayedCustomers({ filters }: Props) {
  const { data, isLoading } = useTopDelayedCustomers(filters, 10)
  const rows = data?.data ?? []

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center gap-2">
        <Users className="h-4 w-4 text-[#1B3A5C]" />
        <div className="text-sm font-semibold text-[#1B3A5C]">
          Top customers contributing to delays
        </div>
      </div>
      <div className="text-[11px] text-[#6B7280]">
        Late = bill_date − dest_actual_departure &gt; 10 days · ranked by $
        revenue at risk
      </div>
      <div className="mt-3 max-h-52 overflow-auto">
        {isLoading ? (
          <div className="flex h-32 items-center justify-center text-[#6B7280]">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        ) : rows.length === 0 ? (
          <div className="py-8 text-center text-xs text-[#9CA3AF]">
            No customers with &gt;10-day delays in current filters
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                <th className="px-1.5 py-1.5 text-left">Customer</th>
                <th className="px-1.5 py-1.5 text-right">Late</th>
                <th className="px-1.5 py-1.5 text-right">Revenue</th>
                <th className="px-1.5 py-1.5 text-right">Avg d</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.customer_name}
                  className="border-b border-[#F3F4F6] last:border-0"
                >
                  <td className="px-1.5 py-1.5 truncate" title={r.customer_name}>
                    {r.customer_name}
                  </td>
                  <td className="px-1.5 py-1.5 text-right tabular-nums">
                    {fmtCount(r.n_late)}
                  </td>
                  <td className="px-1.5 py-1.5 text-right tabular-nums font-semibold text-[#991B1B]">
                    {fmtUsd(r.late_revenue)}
                  </td>
                  <td className="px-1.5 py-1.5 text-right tabular-nums">
                    {fmtNum1(r.avg_days)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
