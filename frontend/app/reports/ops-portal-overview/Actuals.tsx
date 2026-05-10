"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtUsdSigned,
  useOppActuals,
  type OppFilters,
} from "@/lib/ops-portal-overview-api"

interface Props {
  filters: OppFilters
}

const SORT_OPTIONS: { k: string; label: string }[] = [
  { k: "revenue_desc", label: "Top Revenue" },
  { k: "profit_desc",  label: "Top Profit" },
  { k: "loss_desc",    label: "Worst Profit" },
  { k: "volume_desc",  label: "Top Volume" },
  { k: "customer",     label: "Customer A→Z" },
]

export function Actuals({ filters }: Props) {
  const [sort, setSort] = useState<string>("revenue_desc")
  const { data, isLoading, error } = useOppActuals(filters, { sort, limit: 100 })
  const rows = data?.data ?? []

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
        <span className="rounded-md bg-[#1B3A5C] px-2 py-0.5 text-xs font-semibold uppercase text-white">
          Actuals
        </span>
        <span className="text-[10px] uppercase tracking-wider text-[#6B7280]">
          Production / Budget / Variance per cell
        </span>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wider text-[#6B7280]">Sort</span>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.k} value={o.k}>{o.label}</option>
            ))}
          </select>
          {isLoading && <Loader2 className="h-3 w-3 animate-spin text-[#6B7280]" />}
        </div>
      </div>

      {error ? (
        <div className="px-3 py-4 text-sm text-[#DC2626]">Failed to load Actuals</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                <Th>Customer Name</Th>
                <Th align="center">Volume<br /><span className="text-[8px] font-normal">Budget / Variance</span></Th>
                <Th align="center">Revenue<br /><span className="text-[8px] font-normal">Budget / Variance</span></Th>
                <Th align="center">Profit<br /><span className="text-[8px] font-normal">Budget / Variance</span></Th>
                <Th align="center">Margin<br /><span className="text-[8px] font-normal">Budget / Variance</span></Th>
                <Th align="right">OTP %</Th>
                <Th align="right">OTD %</Th>
                <Th align="right">Rev. x L</Th>
                <Th align="right">Prof. x L</Th>
                <Th align="center">Vol. x Day<br /><span className="text-[8px] font-normal">Variance</span></Th>
                <Th align="center">Prof. x Day<br /><span className="text-[8px] font-normal">Variance</span></Th>
                <Th align="center">Proj. EOM Vol.<br /><span className="text-[8px] font-normal">Budget</span></Th>
                <Th align="center">Proj. EOM Profit<br /><span className="text-[8px] font-normal">Budget / Variance</span></Th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={13} className="px-3 py-6 text-center text-[#9CA3AF]">No customers in scope</td>
                </tr>
              ) : rows.map((r) => (
                <tr key={r.customer_name} className="border-b border-[#F3F4F6] hover:bg-[#FAFBFC]">
                  <td className="px-2 py-2 font-semibold text-[#1B3A5C]">{r.customer_name}</td>
                  <StackedCell
                    primary={fmtCount(r.vol)}
                    budget={fmtCount(r.vol_budget)}
                    variance={fmtCount(r.vol_var)}
                    varNeg={r.vol_var < 0}
                  />
                  <StackedCell
                    primary={fmtUsd(r.rev)}
                    budget={fmtUsd(r.rev_budget)}
                    variance={fmtUsdSigned(r.rev_var)}
                    varNeg={r.rev_var < 0}
                  />
                  <StackedCell
                    primary={fmtUsd(r.prof)}
                    budget={fmtUsd(r.prof_budget)}
                    variance={fmtUsdSigned(r.prof_var)}
                    varNeg={r.prof_var < 0}
                  />
                  <StackedCell
                    primary={fmtPct(r.margin_pct)}
                    budget={fmtPct(r.margin_budget_pct)}
                    variance={`${r.margin_var_pct >= 0 ? "+" : ""}${r.margin_var_pct.toFixed(2)}%`}
                    varNeg={r.margin_var_pct < 0}
                  />
                  <td className="px-2 py-2 text-right tabular-nums">{fmtPct(r.otp_pct)}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{fmtPct(r.otd_pct)}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{fmtUsd(r.rev_x_l)}</td>
                  <td className={`px-2 py-2 text-right tabular-nums ${r.prof_x_l < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtUsd(r.prof_x_l)}
                  </td>
                  <td className="px-2 py-2 text-center tabular-nums">{fmtCount(r.vol_x_day)}</td>
                  <td className={`px-2 py-2 text-center tabular-nums ${r.prof_x_day < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtUsd(r.prof_x_day)}
                  </td>
                  <td className="px-2 py-2 text-center tabular-nums">
                    <div>{fmtCount(r.proj_eom_vol)}</div>
                    <div className="text-[#9CA3AF]">{fmtCount(r.vol_budget)}</div>
                  </td>
                  <td className="px-2 py-2 text-center tabular-nums">
                    <div className={r.proj_eom_prof < 0 ? "text-[#DC2626]" : ""}>{fmtUsd(r.proj_eom_prof)}</div>
                    <div className="text-[#9CA3AF]">{fmtUsd(r.prof_budget)} / {fmtUsdSigned(r.proj_eom_prof - r.prof_budget)}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" | "center" }) {
  const cls =
    align === "right" ? "text-right"
    : align === "center" ? "text-center"
    : "text-left"
  return <th className={`px-2 py-2 ${cls}`}>{children}</th>
}

function StackedCell({
  primary,
  budget,
  variance,
  varNeg,
}: {
  primary: string
  budget: string
  variance: string
  varNeg: boolean
}) {
  return (
    <td className="px-2 py-2 text-center tabular-nums">
      <div className="font-semibold text-[#1B3A5C]">{primary}</div>
      <div className="flex items-center justify-center gap-2 text-[10px]">
        <span className="text-[#9CA3AF]">{budget}</span>
        <span className={varNeg ? "font-semibold text-[#DC2626]" : "font-semibold text-[#16A34A]"}>{variance}</span>
      </div>
    </td>
  )
}
