"use client"

import {
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtUsdSigned,
  useOppTeamPerformance,
  type OppFilters,
  type OppTeamPerformance,
} from "@/lib/ops-portal-overview-api"
import { PanelCard, Row } from "./SidePanels"

// Bruno R5 (2026-06-01) #6/#7: two new tables under the KPI MANAGEMENT chart,
// duplicating Team Monthly Performance from "Customers" through "Lates DEL".
//   #6 Team Last Month Performance — locked to the previous full month.
//   #7 Team Variance Performance   — this month − last month, per metric.
// Both honour the Team / Customer / Load-type filters but ignore the page's
// Date filter (their range is server-locked to this_month / last_month).

interface Props {
  filters: OppFilters
}

type Kind = "count" | "usd" | "pct"

// The Customers→Lates DEL subset, in display order. ``Total Cost`` (R5 #13)
// sits between Revenue and Profit to mirror the monthly panel.
const METRICS: { key: keyof OppTeamPerformance; label: string; kind: Kind }[] = [
  { key: "customers",  label: "Customers",  kind: "count" },
  { key: "lanes",      label: "Lanes",      kind: "count" },
  { key: "volume",     label: "Volume",     kind: "count" },
  { key: "revenue",    label: "Revenue",    kind: "usd" },
  { key: "total_cost", label: "Total Cost", kind: "usd" },
  { key: "profit",     label: "Profit",     kind: "usd" },
  { key: "margin_pct", label: "Margin P %", kind: "pct" },
  { key: "rev_x_l",    label: "Rev. x L.",  kind: "usd" },
  { key: "prof_x_l",   label: "Prf. X L.",  kind: "usd" },
  { key: "team_ut",    label: "Team Ut.",   kind: "pct" },
  { key: "otp_pct",    label: "OTP.",       kind: "pct" },
  { key: "lates_pu",   label: "Lates PU",   kind: "count" },
  { key: "otd_pct",    label: "OTD.",       kind: "pct" },
  { key: "lates_del",  label: "Lates DEL.", kind: "count" },
]

function fmtValue(kind: Kind, v: number): string {
  if (kind === "count") return fmtCount(v)
  if (kind === "pct") return fmtPct(v)
  return fmtUsd(v)
}

function fmtSigned(kind: Kind, v: number): string {
  if (kind === "count") return `${v >= 0 ? "+" : ""}${fmtCount(v)}`
  if (kind === "pct") return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`
  return fmtUsdSigned(v)
}

// ---------------------------------------------------------------------------
// #6 — Team Last Month Performance (range locked to previous month)
// ---------------------------------------------------------------------------

export function TeamLastMonthPerformance({ filters }: Props) {
  // Range is server-locked; drop the page's custom dates so the query key
  // stays stable when the page Date filter changes.
  const locked: OppFilters = { ...filters, range: "last_month", startDate: undefined, endDate: undefined }
  const { data, isLoading, error } = useOppTeamPerformance(locked)
  const v = data?.data
  return (
    <PanelCard title="Team Last Month Performance" icon="📅" loading={isLoading} error={error}>
      <table className="w-full text-xs">
        <tbody>
          {METRICS.map((m) => (
            <Row
              key={m.key}
              label={m.label}
              value={v ? fmtValue(m.kind, Number(v[m.key] ?? 0)) : "—"}
            />
          ))}
        </tbody>
      </table>
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// #7 — Team Variance Performance (this month − last month)
// ---------------------------------------------------------------------------

export function TeamVariancePerformance({ filters }: Props) {
  const thisM: OppFilters = { ...filters, range: "this_month", startDate: undefined, endDate: undefined }
  const lastM: OppFilters = { ...filters, range: "last_month", startDate: undefined, endDate: undefined }
  const cur = useOppTeamPerformance(thisM)
  const prev = useOppTeamPerformance(lastM)
  const loading = cur.isLoading || prev.isLoading
  const error = cur.error || prev.error
  const a = cur.data?.data
  const b = prev.data?.data
  const ready = !!a && !!b
  return (
    <PanelCard title="Team Variance Performance" icon="🔀" loading={loading} error={error}>
      <table className="w-full text-xs">
        <tbody>
          {METRICS.map((m) => {
            const delta = ready ? Number(a![m.key] ?? 0) - Number(b![m.key] ?? 0) : 0
            return (
              <Row
                key={m.key}
                label={m.label}
                value={ready ? fmtSigned(m.kind, delta) : "—"}
                signed
                numeric={delta}
              />
            )
          })}
        </tbody>
      </table>
    </PanelCard>
  )
}
