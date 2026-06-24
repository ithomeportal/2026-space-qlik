"use client"

import { useEffect, useState } from "react"
import { Loader2, Maximize2, X } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  useOppServiceIncident,
  type OppFilters,
  type OppServiceIncidentRow,
} from "@/lib/ops-portal-overview-api"

interface Props {
  filters: OppFilters
  /** When present, customer-name cells become clickable (drill to that customer — R9). */
  onPickCustomer?: (customer: string) => void
  /** Same idea for lane cells (unused here — these tables have no lane grain — kept for the shared contract). */
  onPickLane?: (lane: string) => void
}

// Two side-by-side panels mirroring the §5 incident split (Bruno 2026-06-15):
// PU service-fails on the left, DEL service-fails on the right. The backend
// already caps each at the top 100 by fail count; we scroll within the panel
// and R11 lets each one expand to the full uncapped table in a modal.
export function ServiceIncidentTables({ filters, onPickCustomer }: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <IncidentPanel
        filters={filters}
        stopType="pu"
        title="# Service Incident by Customer (PU)"
        icon="🚚"
        failHeader="PU Service Fail"
        pctHeader="% On Time"
        onPickCustomer={onPickCustomer}
      />
      <IncidentPanel
        filters={filters}
        stopType="del"
        title="# Service Incident by Customer (Del)"
        icon="📦"
        failHeader="DEL Service Fail"
        pctHeader="DEL % On Time"
        onPickCustomer={onPickCustomer}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// One panel — capped table + expand button → uncapped modal (own useState).
// ---------------------------------------------------------------------------

function IncidentPanel({
  filters,
  stopType,
  title,
  icon,
  failHeader,
  pctHeader,
  onPickCustomer,
}: {
  filters: OppFilters
  stopType: "pu" | "del"
  title: string
  icon: string
  failHeader: string
  pctHeader: string
  onPickCustomer?: (customer: string) => void
}) {
  const { data, isLoading, error } = useOppServiceIncident(filters, stopType)
  const rows: OppServiceIncidentRow[] = data?.data ?? []
  const [expanded, setExpanded] = useState(false)

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2 text-sm font-semibold text-[#3B82F6]">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          title="Expand full table"
          aria-label="Expand full table"
          className="flex h-5 w-5 items-center justify-center rounded border border-[#BFDBFE] bg-white text-[#2563EB] hover:bg-[#EFF6FF]"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
        <span aria-hidden>{icon}</span>
        <span>{title}</span>
        {isLoading && <Loader2 className="ml-auto h-3 w-3 animate-spin text-[#6B7280]" />}
      </div>
      {error ? (
        <div className="px-3 py-3 text-xs text-[#DC2626]">Failed to load</div>
      ) : (
        <div className="max-h-[320px] overflow-x-hidden overflow-y-auto px-3 py-2">
          <IncidentTable
            rows={rows}
            failHeader={failHeader}
            pctHeader={pctHeader}
            onPickCustomer={onPickCustomer}
          />
        </div>
      )}
      {expanded && (
        <IncidentModal
          title={title}
          icon={icon}
          rows={rows}
          failHeader={failHeader}
          pctHeader={pctHeader}
          onPickCustomer={onPickCustomer}
          onClose={() => setExpanded(false)}
        />
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// The table itself — shared by the capped panel and the uncapped modal.
// ---------------------------------------------------------------------------

function IncidentTable({
  rows,
  failHeader,
  pctHeader,
  onPickCustomer,
}: {
  rows: OppServiceIncidentRow[]
  failHeader: string
  pctHeader: string
  onPickCustomer?: (customer: string) => void
}) {
  return (
    <table className="w-full table-fixed text-xs">
      <colgroup>
        <col className="w-[54%]" />
        <col className="w-[22%]" />
        <col className="w-[24%]" />
      </colgroup>
      <thead className="sticky top-0 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
        <tr>
          <th className="px-2 py-1 text-left">Customer</th>
          <th className="px-2 py-1 text-right">{failHeader}</th>
          <th className="px-2 py-1 text-right">{pctHeader}</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={3} className="px-2 py-3 text-center text-[#9CA3AF]">
              No incidents
            </td>
          </tr>
        ) : (
          rows.map((r) => (
            <tr key={r.customer_name} className="border-t border-[#F3F4F6]">
              <td className="truncate px-2 py-1 text-[#374151]" title={r.customer_name}>
                {onPickCustomer ? (
                  <button
                    type="button"
                    onClick={() => onPickCustomer(r.customer_name)}
                    className="truncate text-left text-[#2563EB] hover:underline"
                    title={r.customer_name}
                  >
                    {r.customer_name}
                  </button>
                ) : (
                  r.customer_name
                )}
              </td>
              <td className="px-2 py-1 text-right tabular-nums text-[#DC2626]">
                {fmtCount(r.fail)}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                <span className={`rounded px-1.5 py-0.5 font-semibold ${pctBandCls(r.pct_on_time)}`}>
                  {fmtPct(r.pct_on_time)}
                </span>
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  )
}

// % On Time band: >=95.5 green, >=93 amber, else red (mirrors the §5 OTP/OTD bands).
function pctBandCls(pct: number): string {
  if (pct >= 95.5) return "bg-[#DCFCE7] text-[#166534]"
  if (pct >= 93) return "bg-[#FEF9C3] text-[#854D0E]"
  return "bg-[#FEE2E2] text-[#991B1B]"
}

// ---------------------------------------------------------------------------
// R11 expand modal — same table, no height cap. Esc / backdrop closes.
// ---------------------------------------------------------------------------

function IncidentModal({
  title,
  icon,
  rows,
  failHeader,
  pctHeader,
  onPickCustomer,
  onClose,
}: {
  title: string
  icon: string
  rows: OppServiceIncidentRow[]
  failHeader: string
  pctHeader: string
  onPickCustomer?: (customer: string) => void
  onClose: () => void
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#E5E7EB] bg-[#F0F9FF] px-4 py-3">
          <div className="flex items-center gap-2">
            <span aria-hidden>{icon}</span>
            <div className="text-sm font-semibold text-[#1B3A5C]">{title}</div>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-[#6B7280] hover:bg-white hover:text-[#111827]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          <IncidentTable
            rows={rows}
            failHeader={failHeader}
            pctHeader={pctHeader}
            onPickCustomer={onPickCustomer}
          />
        </div>
      </div>
    </div>
  )
}
