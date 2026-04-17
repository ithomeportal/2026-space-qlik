"use client"

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: {
    total: number
    page: number
    limit: number
  }
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`)
  }
  return res.json()
}

export interface Report {
  id: string
  qlik_app_id: string | null
  qlik_sheet_id: string | null
  title: string
  description: string | null
  note: string | null
  category: string | null
  tags: string[]
  tag_roles: string[]
  owner_name: string | null
  data_sources: string[]
  last_reload: string | null
  is_active: boolean
  is_favorited?: boolean
  view_count?: number
  use_classic?: boolean
  report_type?: "qlik" | "custom"
  custom_path?: string | null
}

export interface TagRole {
  id: string
  name: string
  description: string | null
  report_count: number
}

export function useReports(category?: string, mobile?: boolean) {
  const params = new URLSearchParams()
  if (category) params.set("category", category)
  if (mobile) params.set("mobile", "true")
  const qs = params.toString()
  return useQuery({
    queryKey: ["reports", category, mobile],
    queryFn: () => apiFetch<Report[]>(`reports${qs ? `?${qs}` : ""}`),
  })
}

export function useReport(id: string) {
  return useQuery({
    queryKey: ["report", id],
    queryFn: () => apiFetch<Report>(`reports/${id}`),
    enabled: !!id,
  })
}

export function useTrending(mobile?: boolean) {
  const qs = mobile ? "?mobile=true" : ""
  return useQuery({
    queryKey: ["trending", mobile],
    queryFn: () => apiFetch<Report[]>(`reports/trending${qs}`),
  })
}

export interface SearchResult {
  id: string
  title: string
  description: string | null
  category?: string | null
  note?: string | null
  url?: string
  icon_data?: string | null
  result_type: "report" | "app"
}

export function useSearch(query: string) {
  return useQuery({
    queryKey: ["search", query],
    queryFn: () => apiFetch<SearchResult[]>(`reports/search?q=${encodeURIComponent(query)}`),
    enabled: query.length >= 2,
  })
}

export interface AppItem {
  id: string
  title: string
  url: string
  description: string | null
  icon_data: string | null
  is_active: boolean
}

export function useApps() {
  return useQuery({
    queryKey: ["apps"],
    queryFn: () => apiFetch<AppItem[]>("apps"),
  })
}

export function useUserTagRoles() {
  return useQuery({
    queryKey: ["user-tag-roles"],
    queryFn: () => apiFetch<TagRole[]>("user/tag-roles"),
  })
}

export function useQlikToken() {
  return useQuery({
    queryKey: ["qlik-token"],
    queryFn: () => apiFetch<{ token: string }>("qlik/token"),
    staleTime: 50 * 60 * 1000, // 50 minutes
    refetchInterval: 50 * 60 * 1000,
  })
}

export interface UserPreferences {
  pinned_reports: string[]
  recent_reports: string[]
  theme: string
}

export function usePreferences() {
  return useQuery({
    queryKey: ["preferences"],
    queryFn: () => apiFetch<UserPreferences>("user/preferences"),
  })
}

export function useUpdatePreferences() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<UserPreferences>) =>
      apiFetch("user/preferences", {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["preferences"] })
    },
  })
}

// ─── Carrier Savings (code-made report) ──────────────────────────────────────

export interface SavingsMonth {
  month_date: string
  type_month_description: string
  base_month: string | null
}

export interface SavingsSummary {
  total_loads: number
  total_cost: number
  total_savings: number
  total_overpay: number
  net_variance: number
  high_vol_lanes: number
  low_vol_lanes: number
  high_vol_savings_lanes: number
  low_vol_savings_lanes: number
  base_month: string | null
  avg_base_lane: number | null
  month_date: string | null
}

export interface SavingsByCustomer {
  customer_id: string
  customer_name: string
  lane_count: number
  loads: number
  cost: number
  savings: number | null
  overpay: number | null
  net_variance: number
}

export interface SavingsLane {
  customer_id: string
  customer_name: string
  origin_name: string
  dest_name: string
  cost_monthly_usd: number
  number_monthly_loads: number
  avg_monthly_usd: number
  variance: number
  base_lane: number
  base_month: string
  type_month_description: string
  month_date: string
}

export function useSavingsMonths() {
  return useQuery({
    queryKey: ["savings", "months"],
    queryFn: () => apiFetch<SavingsMonth[]>("custom/carriers-savings/months"),
    staleTime: 10 * 60 * 1000,
  })
}

export type SavingsDivision = "CORP" | "DFW"
export type SavingsCorpTeam = "TEAM1" | "TEAM2" | "TEAM3" | "TEAM4" | "TEAM5"

export function useSavingsSummary(
  month?: string,
  customerId?: string,
  division?: SavingsDivision,
  team?: SavingsCorpTeam,
) {
  const qs = new URLSearchParams()
  if (month) qs.set("month", month)
  if (customerId) qs.set("customer_id", customerId)
  if (division) qs.set("division", division)
  if (team) qs.set("team", team)
  const suffix = qs.toString() ? `?${qs}` : ""
  return useQuery({
    queryKey: ["savings", "summary", month, customerId, division, team],
    queryFn: () => apiFetch<SavingsSummary>(`custom/carriers-savings/summary${suffix}`),
  })
}

export function useSavingsByCustomer(
  month?: string,
  limit = 50,
  division?: SavingsDivision,
  team?: SavingsCorpTeam,
) {
  const qs = new URLSearchParams({ limit: String(limit) })
  if (month) qs.set("month", month)
  if (division) qs.set("division", division)
  if (team) qs.set("team", team)
  return useQuery({
    queryKey: ["savings", "by-customer", month, limit, division, team],
    queryFn: () => apiFetch<SavingsByCustomer[]>(`custom/carriers-savings/by-customer?${qs}`),
  })
}

export interface SavingsLanesFilters {
  month?: string
  customerId?: string
  origin?: string
  dest?: string
  sort?: string
  page?: number
  limit?: number
  division?: SavingsDivision
  team?: SavingsCorpTeam
}

export interface SavingsTeamRow {
  division: "CORP" | "DFW"
  team_id: string
  loads: number
  total_savings: number
  total_overpay: number
  net_variance: number
}

export function useSavingsByTeam(
  month?: string,
  customerId?: string,
  division?: SavingsDivision,
  team?: SavingsCorpTeam,
) {
  const qs = new URLSearchParams()
  if (month) qs.set("month", month)
  if (customerId) qs.set("customer_id", customerId)
  if (division) qs.set("division", division)
  if (team) qs.set("team", team)
  const suffix = qs.toString() ? `?${qs}` : ""
  return useQuery({
    queryKey: ["savings", "by-team", month, customerId, division, team],
    queryFn: () => apiFetch<SavingsTeamRow[]>(`custom/carriers-savings/by-team${suffix}`),
  })
}

export interface SavingsMonthlyTotals {
  month_date: string
  volume: number
  total_savings: number
  total_overpay: number
  net_variance: number
}

export function useSavingsMonthlyTotals(
  customerId?: string,
  division?: SavingsDivision,
  team?: SavingsCorpTeam,
  windowMonths = 9,
) {
  const qs = new URLSearchParams({ window: String(windowMonths) })
  if (customerId) qs.set("customer_id", customerId)
  if (division) qs.set("division", division)
  if (team) qs.set("team", team)
  return useQuery({
    queryKey: ["savings", "monthly-totals", customerId, division, team, windowMonths],
    queryFn: () =>
      apiFetch<SavingsMonthlyTotals[]>(`custom/carriers-savings/monthly-totals?${qs}`),
  })
}

export function useSavingsLanes(filters: SavingsLanesFilters) {
  const qs = new URLSearchParams()
  if (filters.month) qs.set("month", filters.month)
  if (filters.customerId) qs.set("customer_id", filters.customerId)
  if (filters.origin) qs.set("origin", filters.origin)
  if (filters.dest) qs.set("dest", filters.dest)
  if (filters.sort) qs.set("sort", filters.sort)
  if (filters.division) qs.set("division", filters.division)
  if (filters.team) qs.set("team", filters.team)
  qs.set("page", String(filters.page ?? 1))
  qs.set("limit", String(filters.limit ?? 100))
  return useQuery({
    queryKey: ["savings", "lanes", filters],
    queryFn: () => apiFetch<SavingsLane[]>(`custom/carriers-savings/lanes?${qs}`),
  })
}

// === 2026 Official Budget Follow Up ===

export interface BudgetFilterOptions {
  teams: string[]
  customers: string[]
  year_start: string
  year_end: string
}

export interface BudgetSummary {
  loads_actual: number
  loads_budget: number
  loads_variance: number
  loads_achievement_pct: number
  revenue_actual: number
  revenue_budget: number
  revenue_variance: number
  revenue_achievement_pct: number
  profit_actual: number
  profit_budget: number
  profit_variance: number
  profit_achievement_pct: number
  margin_actual_pct: number
  margin_budget_pct: number
  margin_variance_pct: number
  active_customers: number
  total_customers: number
  active_days: number
  total_days: number
  days_elapsed: number
  days_remaining: number
  start_date: string
  end_date: string
}

export interface BudgetCustomerRow {
  customer_name: string
  loads_actual: number
  loads_budget: number
  loads_variance: number
  revenue_actual: number
  revenue_budget: number
  revenue_variance: number
  profit_actual: number
  profit_budget: number
  profit_variance: number
  margin_actual_pct: number
  margin_budget_pct: number
}

export interface BudgetTeamRow {
  team_id: string
  loads_actual: number
  loads_budget: number
  revenue_actual: number
  revenue_budget: number
  profit_actual: number
  profit_budget: number
}

export interface BudgetMonthPoint {
  month_date: string
  loads_actual: number
  loads_budget: number
  revenue_actual: number
  revenue_budget: number
  profit_actual: number
  profit_budget: number
}

export interface BudgetFilters {
  startDate?: string
  endDate?: string
  teams?: string[]
  customer?: string
}

function budgetQs(filters: BudgetFilters, extra?: Record<string, string>) {
  const qs = new URLSearchParams()
  if (filters.startDate) qs.set("start_date", filters.startDate)
  if (filters.endDate) qs.set("end_date", filters.endDate)
  if (filters.teams && filters.teams.length) qs.set("teams", filters.teams.join(","))
  if (filters.customer) qs.set("customer", filters.customer)
  if (extra) {
    for (const [k, v] of Object.entries(extra)) qs.set(k, v)
  }
  const s = qs.toString()
  return s ? `?${s}` : ""
}

export function useBudgetFilters() {
  return useQuery({
    queryKey: ["budget", "filters"],
    queryFn: () => apiFetch<BudgetFilterOptions>("custom/budget-followup/filters"),
    staleTime: 10 * 60 * 1000,
  })
}

export function useBudgetSummary(filters: BudgetFilters) {
  return useQuery({
    queryKey: ["budget", "summary", filters],
    queryFn: () => apiFetch<BudgetSummary>(`custom/budget-followup/summary${budgetQs(filters)}`),
  })
}

export function useBudgetByCustomer(
  filters: BudgetFilters,
  sort: string,
  page: number,
  limit = 100,
) {
  return useQuery({
    queryKey: ["budget", "by-customer", filters, sort, page, limit],
    queryFn: () =>
      apiFetch<BudgetCustomerRow[]>(
        `custom/budget-followup/by-customer${budgetQs(filters, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
  })
}

export function useBudgetByTeam(filters: BudgetFilters) {
  // Team filter intentionally excluded — we always want all teams in this roll-up.
  const rest: BudgetFilters = {
    startDate: filters.startDate,
    endDate: filters.endDate,
    customer: filters.customer,
  }
  return useQuery({
    queryKey: ["budget", "by-team", rest],
    queryFn: () => apiFetch<BudgetTeamRow[]>(`custom/budget-followup/by-team${budgetQs(rest)}`),
  })
}

export function useBudgetMonthly(filters: BudgetFilters) {
  return useQuery({
    queryKey: ["budget", "monthly", filters],
    queryFn: () =>
      apiFetch<BudgetMonthPoint[]>(`custom/budget-followup/monthly${budgetQs(filters)}`),
  })
}

export function useToggleFavorite() {
  const queryClient = useQueryClient()
  const { data: prefs } = usePreferences()

  return useMutation({
    mutationFn: async (reportId: string) => {
      const current = prefs?.data?.pinned_reports ?? []
      const updated = current.includes(reportId)
        ? current.filter((id) => id !== reportId)
        : [...current, reportId]

      return apiFetch("user/preferences", {
        method: "PATCH",
        body: JSON.stringify({ pinned_reports: updated }),
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["preferences"] })
      queryClient.invalidateQueries({ queryKey: ["reports"] })
    },
  })
}
