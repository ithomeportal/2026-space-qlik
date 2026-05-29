"use client"

import { useQuery } from "@tanstack/react-query"

// ---------------------------------------------------------------------------
// Reports Index — leadership directory of every code-made report.
//
// The backend (`/custom/index/catalog`) returns the FULL active catalog with
// each report's live metadata + assigned TagRoles (the "audience"). This file
// adds the only two things the catalog has no data source for:
//   • `kpis`    — a curated one-line "main KPIs / what it answers" summary
//   • `related` — explicit cross-links to sibling/companion reports (by key)
//
// Everything else (title, description, note, audience, main link) is live, so
// the Index can never go stale on names or paths. When you add a report, it
// shows up automatically; add an entry below only to enrich its KPI line and
// wire its related links.
// ---------------------------------------------------------------------------

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total?: number }
}

async function apiFetch<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const INDEX_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

export interface CatalogReport {
  key: string
  title: string
  description: string | null
  note: string | null
  category: string | null
  tags: string[]
  owner_name: string | null
  custom_path: string
  tag_roles: string[]
}

export function useReportsCatalog() {
  return useQuery({
    queryKey: ["reports-index-catalog"],
    queryFn: () => apiFetch<CatalogReport[]>("custom/index/catalog"),
    staleTime: 5 * 60 * 1000,
    ...INDEX_RETRY,
  })
}

// ---------------------------------------------------------------------------
// Curated overlay — keyed by report key (the `/reports/<key>` slug).
// `kpis`: the headline metrics / question each report answers.
// `related`: keys of companion reports (resolved to live titles + paths).
// ---------------------------------------------------------------------------

export interface ReportOverlay {
  kpis: string
  related: string[]
}

export const REPORT_OVERLAY: Record<string, ReportOverlay> = {
  "esavings-carriers": {
    kpis: "Loads, savings $, overpay $, net variance vs quarterly base lane",
    related: ["carrier-risk", "track-award-loads", "rfp-performance"],
  },
  "budget-followup-2026": {
    kpis: "2026 actuals vs budget: loads, revenue, profit, margin %, projected, pending days",
    related: ["ops-portal-overview", "ops-margins", "xray-corp-mng"],
  },
  "xray-corp-mng": {
    kpis: "CORP KPIs: OTP, OTD, profit-TM, lanes, trends, risk, contract/spot split (TEAM1–5)",
    related: ["xray-dfw-mng", "ops-portal-overview", "ops-margins"],
  },
  "xray-dfw-mng": {
    kpis: "DFW KPIs: OTP, OTD, profit-TM, lanes, trends, risk, contract/spot split (sub-teams TM1–4)",
    related: ["xray-corp-mng", "xray-dfw-tm1", "xray-dfw-tm2", "xray-dfw-tm3", "xray-dfw-tm4", "kam-performance-dfw"],
  },
  "xray-dfw-tm1": {
    kpis: "XRay DFW locked to TM1 — same engine, server-pinned to one sub-team",
    related: ["xray-dfw-mng", "xray-dfw-tm2", "xray-dfw-tm3", "xray-dfw-tm4"],
  },
  "xray-dfw-tm2": {
    kpis: "XRay DFW locked to TM2 — same engine, server-pinned to one sub-team",
    related: ["xray-dfw-mng", "xray-dfw-tm1", "xray-dfw-tm3", "xray-dfw-tm4"],
  },
  "xray-dfw-tm3": {
    kpis: "XRay DFW locked to TM3 — same engine, server-pinned to one sub-team",
    related: ["xray-dfw-mng", "xray-dfw-tm1", "xray-dfw-tm2", "xray-dfw-tm4"],
  },
  "xray-dfw-tm4": {
    kpis: "XRay DFW locked to TM4 — same engine, server-pinned to one sub-team",
    related: ["xray-dfw-mng", "xray-dfw-tm1", "xray-dfw-tm2", "xray-dfw-tm3"],
  },
  "ceo-executive": {
    kpis: "Company-wide trends, 20-week weekly + improvement, orders, Top-5 by division/team, customer drill-down",
    related: ["ops-portal-overview", "xray-corp-mng", "losses-lanes"],
  },
  "hr-access-doors": {
    kpis: "Badge punch-ins: on-time vs late %, check-minutes, by-department, 30-day trend",
    related: ["dfw-access-doors", "admin-access-doors"],
  },
  "dfw-access-doors": {
    kpis: "DFW badge punch-ins: on-time vs late %, check-minutes (DFW roster)",
    related: ["hr-access-doors", "admin-access-doors"],
  },
  "admin-access-doors": {
    kpis: "Admin/Finance badge punch-ins: on-time vs late %, check-minutes",
    related: ["hr-access-doors", "dfw-access-doors"],
  },
  "podium-dfw": {
    kpis: "DFW reps podium — loads, revenue, margin set with a date filter",
    related: ["dfw-podium-top", "kam-performance-dfw", "xray-dfw-mng"],
  },
  "dfw-podium-top": {
    kpis: "5 DFW leaderboards (top reps) — always current period, no date filter",
    related: ["podium-dfw", "kam-performance-dfw"],
  },
  "losses-lanes": {
    kpis: "Negative-margin lanes ranked by loss $ — customer, lane, team",
    related: ["ops-margins", "attrition-wow", "ceo-executive"],
  },
  "ops-margins": {
    kpis: "Margin % and margin $ by customer/team/lane; negative-margin outliers",
    related: ["ops-direct-compare", "ops-customer-score", "losses-lanes"],
  },
  "ops-direct-compare": {
    kpis: "Period-over-period direct comparison of ops volume, revenue, margin",
    related: ["ops-margins", "ops-customer-score", "ops-portal-overview"],
  },
  "ops-customer-score": {
    kpis: "Customer scorecard — volume, revenue, margin, health/score by customer",
    related: ["ops-margins", "ops-direct-compare", "kam-performance-dfw"],
  },
  "sales-attrition-to-ops": {
    kpis: "Customers attriting from Sales into Ops — churn bridge by customer/lane",
    related: ["attrition-wow", "ops-customer-score"],
  },
  "attrition-wow": {
    kpis: "Week-over-week customer attrition, losses tab, lane-grained spot, RUAN/client view",
    related: ["sales-attrition-to-ops", "losses-lanes", "ceo-executive"],
  },
  "track-award-loads": {
    kpis: "Awarded-lane volume tracking vs commitment — awards delivered / pending",
    related: ["rfp-performance", "esavings-carriers", "carrier-risk"],
  },
  "rfp-performance": {
    kpis: "RFP/bid performance — win/loss, awarded vs run lanes, contract compliance",
    related: ["track-award-loads", "esavings-carriers", "carrier-risk"],
  },
  "voip-calls-logs": {
    kpis: "VoIP call logs — volume, duration, inbound/outbound by user/extension",
    related: ["it-tickets-mgmt"],
  },
  "carrier-risk": {
    kpis: "Carrier concentration risk — HHI, top-1 share, risk band per dispatcher/lane",
    related: ["esavings-carriers", "track-award-loads", "rfp-performance"],
  },
  "it-tickets-mgmt": {
    kpis: "FreshService tickets — volume, status, SLA, resolution time by agent/category",
    related: ["voip-calls-logs"],
  },
  "ops-portal-overview": {
    kpis: "Ops overview merging Production + Budget + Savings — KPIs, variance, grain toggle",
    related: ["xray-corp-mng", "budget-followup-2026", "ops-margins", "ceo-executive"],
  },
  "kam-performance-dfw": {
    kpis: "DFW KAM performance — per-account volume, revenue, margin; editable targets",
    related: ["ops-customer-score", "xray-dfw-mng", "podium-dfw"],
  },
  "bonus-calculator": {
    kpis: "CEO+HR bonus engine — 6th→6th period, board-pinned FX, on-time P&D actual bonus %",
    related: ["kam-performance-dfw", "podium-dfw"],
  },
  "admin-cashflow": {
    kpis: "A/R aging discipline — delivery/BOL/invoice-vs-bill aging, unbilled inventory $",
    related: ["budget-followup-2026", "ops-portal-overview"],
  },
}
