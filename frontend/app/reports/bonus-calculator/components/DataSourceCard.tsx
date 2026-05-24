import { Database, CheckCircle2 } from "lucide-react"
import type { BonusReport } from "@/lib/bonus-api"
import { COLORS } from "../format"

const FIELD_LABELS: Record<string, string> = {
  teamId: "team_id",
  teamName: "teamName",
  weekLabel: "weekLabel",
  loads: "# Loads",
  revenue: "$ Revenue",
  grossProfit: "$ Profit",
  marginPct: "Margin %",
  pickupServicePct: "OTP%",
  deliveryServicePct: "OTD%",
  fxRate: "fxRate",
}

export function DataSourceCard({ report }: { report: BonusReport }) {
  const connected = report.dataSource.status.toLowerCase() === "connected"
  return (
    <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="rounded-2xl border border-[#EDE9FE] bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4" style={{ color: COLORS.cardTitle }} />
          <h3 className="text-sm font-bold text-[#1F2937]">McLeod TMS data source</h3>
        </div>
        <p className="mt-1 text-xs text-[#6B7280]">
          Loads, revenue, gross profit, margin %, pickup service and delivery service by operating team and week come
          live from the datalake (same source as XRay CORP Mng).
        </p>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-[#F8FAFC] px-3 py-2">
            <p className="text-[10px] font-bold uppercase tracking-wider text-[#94A3B8]">Status</p>
            <p className="mt-0.5 flex items-center gap-1 text-sm font-semibold" style={{ color: connected ? COLORS.wildcardTitle : "#6B7280" }}>
              {connected && <CheckCircle2 className="h-4 w-4" />}
              {report.dataSource.status}
            </p>
          </div>
          <div className="rounded-lg bg-[#F8FAFC] px-3 py-2">
            <p className="text-[10px] font-bold uppercase tracking-wider text-[#94A3B8]">Last Load</p>
            <p className="mt-0.5 text-sm font-semibold text-[#1F2937]">{report.dataSource.lastSyncLabel}</p>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border p-5 shadow-sm" style={{ background: COLORS.wildcardBg, borderColor: "#A7F3D0" }}>
        <h3 className="text-sm font-bold" style={{ color: COLORS.wildcardTitle }}>
          Required Fields
        </h3>
        <p className="mt-1 text-xs text-[#475569]">These minimum fields drive every bonus calculation.</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {report.dataSource.requiredFields.map((f) => (
            <span key={f} className="rounded-full bg-white px-2.5 py-1 text-[11px] font-medium text-[#0F766E] shadow-sm">
              {FIELD_LABELS[f] ?? f}
            </span>
          ))}
        </div>
      </div>
    </section>
  )
}
