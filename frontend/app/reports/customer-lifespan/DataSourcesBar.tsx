"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp } from "lucide-react"
import {
  fmtDate,
  fmtInt,
  fmtUsd,
  useFreshness,
  type Reconciliation,
} from "@/lib/customer-lifespan-api"

function parseRecon(raw: string | null): Reconciliation | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as Reconciliation
  } catch {
    return null
  }
}

function fmtStamp(ts: string | null | undefined): string {
  if (!ts) return "—"
  return new Date(ts).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago",
  }) + " CT"
}

/** "Data as of" + where the rows come from + the nightly Excel-vs-datalake check (§54). */
export function DataSourcesBar({ asOf }: { asOf: string | undefined }) {
  const { data } = useFreshness()
  const [open, setOpen] = useState(false)
  const f = data?.data
  const recon = parseRecon(f?.reconciliation ?? null)
  const excel = f?.sources.find((s) => s.source === "excel")
  const v4 = f?.sources.find((s) => s.source === "v4")
  const failed = f?.last_sync?.status === "failed"
  const reconOk = recon !== null && recon.missing_in_datalake === 0
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-2 text-[11px] text-[#6B7280]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium text-[#111827]">Data as of {fmtDate(asOf)}</span>
        <span>· history 2016 → {fmtDate(f?.excel_last_ship)} from the 2016-2026 workbook</span>
        <span>· datalake (McLeod v4) since {fmtDate(f?.cutover)}, synced {fmtStamp(f?.last_ok_sync_at)}</span>
        {recon && (
          <span className={`rounded-full px-2 py-0.5 ${reconOk ? "bg-[#D1FAE5] text-[#065F46]" : "bg-[#FEF3C7] text-[#92400E]"}`}>
            cut-date check: {fmtInt(recon.matched)}/{fmtInt(recon.excel_orders)} orders match
          </span>
        )}
        {failed && (
          <span className="rounded-full bg-[#FEE2E2] px-2 py-0.5 text-[#991B1B]">last sync failed</span>
        )}
        <button onClick={() => setOpen((o) => !o)} className="ml-auto flex items-center gap-1 text-[#1B3A5C]">
          Data sources {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>
      </div>
      {open && f && (
        <div className="mt-2 grid gap-2 border-t border-[#F3F4F6] pt-2 md:grid-cols-3">
          <div>
            <div className="font-semibold text-[#111827]">Workbook (Excel)</div>
            {fmtInt(excel?.orders)} orders · {fmtDate(excel?.first_ship)} → {fmtDate(excel?.last_ship)}
            <br />363,028 movements summed per order; customers keyed by McLeod ID.
            {(excel?.voided ?? 0) > 0 && <><br />{fmtInt(excel?.voided)} voided in McLeod since — excluded.</>}
          </div>
          <div>
            <div className="font-semibold text-[#111827]">Datalake (mcleod_gld_budget_report_v4)</div>
            {fmtInt(v4?.orders)} orders · {fmtDate(v4?.first_ship)} → {fmtDate(v4?.last_ship)}
            <br />TMS, delivered + in progress, ship date = origin departure. Re-read nightly 03:30 CT.
            {f.last_sync?.error && <><br /><span className="text-[#991B1B]">{f.last_sync.error}</span></>}
          </div>
          {recon && (
            <div>
              <div className="font-semibold text-[#111827]">
                Cut-date check · {fmtDate(recon.window[0])} → {fmtDate(recon.window[1])}
              </div>
              {fmtInt(recon.matched)} of {fmtInt(recon.excel_orders)} workbook orders found in the datalake
              {recon.missing_in_datalake > 0 && `, ${fmtInt(recon.missing_in_datalake)} missing`}
              {recon.voided_in_datalake > 0 && `, ${fmtInt(recon.voided_in_datalake)} voided since`}.
              <br />Revenue {fmtUsd(recon.excel_revenue)} vs {fmtUsd(recon.datalake_revenue)}
              {" "}(Δ {fmtUsd(recon.revenue_diff)}; the datalake stores whole dollars).
              <br />{fmtInt(recon.gap_fill_orders)} orders the extract missed at its cut were added from the
              datalake ({fmtUsd(recon.gap_fill_revenue)}).
            </div>
          )}
        </div>
      )}
    </div>
  )
}
