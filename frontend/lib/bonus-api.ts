"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
}

const PROXY = "/api/proxy/custom/bonus-calculator"

async function apiGet<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`${PROXY}${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

async function apiSend<T>(method: string, path: string, body?: unknown): Promise<ApiResponse<T>> {
  const res = await fetch(`${PROXY}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const BONUS_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BonusPeriodOption {
  key: string
  label: string
}

export interface BonusFilters {
  periods: BonusPeriodOption[]
  currentPeriod: string
  teams: { id: string; name: string }[]
}

export interface Bracket {
  threshold: number
  bonusPct: number
}

export interface WeeklyRule {
  label: string
  loads: number
  revenue: number
  grossProfit: number
  marginPct: number // decimal
  meetsLoadMinimum: boolean // weekly loads >= 100 — gates every role's bonus
  loadBonusPct: number
  marginBonusPct: number
  serviceBonusPct: number // period/monthly service bracket — drives payout
  serviceAveragePct: number // percentage — per-week (OTP+OTD)/2, display only
  serviceBonusPctWeekly: number // per-week service bracket, load-gated — display only
}

export interface ProfitBracketBonus {
  threshold: number
  label: string
  payoutUsd: number
}

export interface BonusEmployee {
  name: string
  role: "kam" | "freight_match" | "tracking_tracing"
  salaryMxn: number
  weeklyUsd: number[]
  regularWeeklyUsd: number[]
  bonusUsd: number
  wildcardWeeklyUsd: number
  wildcardBonusUsd: number
  wildcardAppliedUsd: number
  wildcardRoleBonusPct: number
  wildcardBasePayUsd: number
  wildcardRuleLabel: string | null
  kamBonusUsd: number
  kamBonusMxn: number
  kamBonusFxRate: number
  kamBonusRuleLabel: string | null
  profitBracketBonuses: ProfitBracketBonus[]
  profitBracketBonusUsd: number
  addOnBonusUsd: number
  totalBonusUsd: number
  bonusMxn: number
}

export interface BonusTeam {
  id: string
  name: string
  pickupServicePct: number
  deliveryServicePct: number
  fxRate: number
  serviceAveragePct: number
  wildcardEligible: boolean
  wildcardServiceBracketPct: number
  wildcardEquivalentLoads: number
  wildcardEquivalentMarginPct: number
  totalLoads: number
  totalRevenue: number
  totalProfit: number
  marginPct: number // decimal
  // Calendar-month cumulative KPIs (Bruno 2026-05-28) — 1st→last day, NOT the
  // sum of the Mon→Sun weekly buckets. Display only; payout math stays weekly.
  monthlyLoads: number
  monthlyRevenue: number
  monthlyProfit: number
  monthlyMarginPct: number // decimal
  monthlyServicePct: number // percentage (e.g. 94.44)
  teamBonusUsd: number
  profitBracketBonuses: ProfitBracketBonus[]
  weeklyRules: WeeklyRule[]
  weeks: WeeklyRule[]
  employees: BonusEmployee[]
}

export interface BonusReport {
  month: string
  source: string
  dataSource: {
    mode: string
    status: string
    requiredFields: string[]
    lastSyncLabel: string
  }
  criteria: {
    loadCountBrackets: Bracket[]
    marginBrackets: Bracket[]
    serviceBrackets: Bracket[]
    payPerLoad: Record<string, number>
  }
  teams: BonusTeam[]
  // Σ of per-team calendar-month profit (Bruno 2026-05-28 KPI basis).
  monthlyTotalProfit: number
  nightShift: {
    fxRate: number
    trackingTracingAverageBonusUsd: number
    trackingTracingTeamBonuses: { teamName: string; weeklyUsd: number[]; bonusUsd: number }[]
    trackingTracingAverageWeeklyBonuses: number[]
    employees: {
      group: string
      name: string
      salaryMxn: number
      receivesBonus: boolean
      bonusUsd: number
      bonusMxn: number
    }[]
    totalBonusUsd: number
  }
  totals: {
    teamBonusUsd: number
    nightShiftBonusUsd: number
    salesBonusUsd: number
    grandBonusUsd: number
    totalProfit: number
    bonusAsPctOfProfit: number
  }
  period: { key: string; label: string; start: string; end: string; weekLabels: string[] }
  fx: { teamFx: number; nightFx: number; pinned: boolean; suggestedDofFx: number | null; updatedBy: string | null }
  lock: { status: string; approvedBy: string | null; approvedAt: string | null }
}

export interface RosterEmployee {
  id: string
  name: string
  role: "kam" | "freight_match" | "tracking_tracing"
  salaryMxn: number
}

export interface RosterData {
  teams: { id: string; name: string; employees: RosterEmployee[] }[]
  afterhours: { id: string; group: string; name: string; salaryMxn: number; receivesBonus: boolean }[]
  settings: { teamFx: number; nightFx: number; pinned: boolean; suggestedDofFx: number | null; updatedBy?: string | null }
  lock: { status: string; approvedBy: string | null; approvedAt: string | null }
  period: { key: string; label: string }
  roles: string[]
}

// ---------------------------------------------------------------------------
// Query hooks
// ---------------------------------------------------------------------------

export function useBonusFilters() {
  return useQuery({
    queryKey: ["bonus", "filters"],
    queryFn: () => apiGet<BonusFilters>("/filters"),
    ...BONUS_RETRY,
  })
}

export function useBonusReport(period: string | undefined) {
  return useQuery({
    queryKey: ["bonus", "report", period ?? "current"],
    queryFn: () => apiGet<BonusReport>(`/report${period ? `?period=${period}` : ""}`),
    ...BONUS_RETRY,
  })
}

// History tab (Bruno 2026-05-28) — immutable monthly snapshots + open month.
export interface BonusHistoryRow {
  periodKey: string
  label?: string
  teamId: string
  teamName: string
  profitUsd: number
  totalBonusUsd: number
  pctBonus: number | null
  finalizedAt?: string | null
}

export interface BonusHistory {
  snapshots: BonusHistoryRow[]
  current: {
    periodKey: string
    label: string
    open: boolean
    rows: Omit<BonusHistoryRow, "periodKey" | "finalizedAt" | "label">[]
  } | null
}

export function useBonusHistory() {
  return useQuery({
    queryKey: ["bonus", "history"],
    queryFn: () => apiGet<BonusHistory>("/history"),
    ...BONUS_RETRY,
  })
}

export function useBonusRoster(period: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["bonus", "roster", period ?? "current"],
    queryFn: () => apiGet<RosterData>(`/roster${period ? `?period=${period}` : ""}`),
    enabled,
    ...BONUS_RETRY,
  })
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useBonusMutations() {
  const qc = useQueryClient()
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["bonus", "report"] })
    qc.invalidateQueries({ queryKey: ["bonus", "roster"] })
  }

  const createRoster = useMutation({
    mutationFn: (b: { team_id: string; name: string; role: string; salary_mxn: number }) =>
      apiSend("POST", "/roster", b),
    onSuccess: invalidate,
  })
  const updateRoster = useMutation({
    mutationFn: ({ id, ...b }: { id: string; team_id: string; name: string; role: string; salary_mxn: number }) =>
      apiSend("PUT", `/roster/${id}`, b),
    onSuccess: invalidate,
  })
  const deleteRoster = useMutation({
    mutationFn: (id: string) => apiSend("DELETE", `/roster/${id}`),
    onSuccess: invalidate,
  })
  const updateAfterhours = useMutation({
    mutationFn: ({ id, ...b }: { id: string; name: string; salary_mxn: number; receives_bonus: boolean }) =>
      apiSend("PUT", `/afterhours/${id}`, b),
    onSuccess: invalidate,
  })
  const saveFx = useMutation({
    mutationFn: (b: { period_key: string; team_fx: number; night_fx: number }) => apiSend("PUT", "/settings", b),
    onSuccess: invalidate,
  })
  const lock = useMutation({
    mutationFn: (period_key: string) => apiSend("POST", "/lock", { period_key }),
    onSuccess: invalidate,
  })
  const unlock = useMutation({
    mutationFn: (period_key: string) => apiSend("DELETE", `/lock/${period_key}`),
    onSuccess: invalidate,
  })

  return { createRoster, updateRoster, deleteRoster, updateAfterhours, saveFx, lock, unlock }
}
