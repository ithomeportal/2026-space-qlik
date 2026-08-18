"use client"

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { mutationErrorToast } from "@/lib/mutation-error"

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
  report_type?: "custom"
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
    onError: mutationErrorToast("Save preferences"),
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

/**
 * Multi-select include/exclude scope filters, shared by every useSavings* hook.
 * The legacy single-value props (`customerId`, `team`) on the hook signatures
 * remain valid; the backend folds them into the include lists.
 */
// "Lanes with change" filter (Bruno 2026-06-08): positive = variance >= 0,
// negative = variance < 0. Threaded through every endpoint via the scope
// object so the whole report (KPIs, teams, customers, trend, lanes) honors it.
export type SavingsVarianceSign = "positive" | "negative"

export interface SavingsScopeFilters {
  teamIds?: string[]
  excludeTeamIds?: string[]
  customerIds?: string[]
  excludeCustomerIds?: string[]
  varianceSign?: SavingsVarianceSign
}

function appendScope(qs: URLSearchParams, scope?: SavingsScopeFilters) {
  if (!scope) return
  for (const v of scope.teamIds ?? []) qs.append("team_ids", v)
  for (const v of scope.excludeTeamIds ?? []) qs.append("exclude_team_ids", v)
  for (const v of scope.customerIds ?? []) qs.append("customer_ids", v)
  for (const v of scope.excludeCustomerIds ?? []) qs.append("exclude_customer_ids", v)
  if (scope.varianceSign) qs.set("variance_sign", scope.varianceSign)
}

function scopeKey(scope?: SavingsScopeFilters) {
  if (!scope) return ""
  return [
    (scope.teamIds ?? []).join(","),
    (scope.excludeTeamIds ?? []).join(","),
    (scope.customerIds ?? []).join(","),
    (scope.excludeCustomerIds ?? []).join(","),
    scope.varianceSign ?? "",
  ].join("|")
}

export interface SavingsCustomerOption {
  customer_id: string
  customer_name: string
}

export function useSavingsCustomers(division?: SavingsDivision) {
  const qs = new URLSearchParams()
  if (division) qs.set("division", division)
  const suffix = qs.toString() ? `?${qs}` : ""
  return useQuery({
    queryKey: ["savings", "customers", division],
    queryFn: () =>
      apiFetch<SavingsCustomerOption[]>(`custom/carriers-savings/customers${suffix}`),
    staleTime: 10 * 60 * 1000,
  })
}

export function useSavingsSummary(
  month?: string,
  customerId?: string,
  division?: SavingsDivision,
  team?: SavingsCorpTeam,
  origin?: string,
  dest?: string,
  scope?: SavingsScopeFilters,
) {
  const qs = new URLSearchParams()
  if (month) qs.set("month", month)
  if (customerId) qs.set("customer_id", customerId)
  if (division) qs.set("division", division)
  if (team) qs.set("team", team)
  if (origin) qs.set("origin", origin)
  if (dest) qs.set("dest", dest)
  appendScope(qs, scope)
  const suffix = qs.toString() ? `?${qs}` : ""
  return useQuery({
    queryKey: ["savings", "summary", month, customerId, division, team, origin, dest, scopeKey(scope)],
    queryFn: () => apiFetch<SavingsSummary>(`custom/carriers-savings/summary${suffix}`),
  })
}

export function useSavingsByCustomer(
  month?: string,
  limit = 50,
  division?: SavingsDivision,
  team?: SavingsCorpTeam,
  origin?: string,
  dest?: string,
  scope?: SavingsScopeFilters,
) {
  const qs = new URLSearchParams({ limit: String(limit) })
  if (month) qs.set("month", month)
  if (division) qs.set("division", division)
  if (team) qs.set("team", team)
  if (origin) qs.set("origin", origin)
  if (dest) qs.set("dest", dest)
  appendScope(qs, scope)
  return useQuery({
    queryKey: ["savings", "by-customer", month, limit, division, team, origin, dest, scopeKey(scope)],
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
  scope?: SavingsScopeFilters
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
  origin?: string,
  dest?: string,
  scope?: SavingsScopeFilters,
) {
  const qs = new URLSearchParams()
  if (month) qs.set("month", month)
  if (customerId) qs.set("customer_id", customerId)
  if (division) qs.set("division", division)
  if (team) qs.set("team", team)
  if (origin) qs.set("origin", origin)
  if (dest) qs.set("dest", dest)
  appendScope(qs, scope)
  const suffix = qs.toString() ? `?${qs}` : ""
  return useQuery({
    queryKey: ["savings", "by-team", month, customerId, division, team, origin, dest, scopeKey(scope)],
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
  origin?: string,
  dest?: string,
  scope?: SavingsScopeFilters,
) {
  const qs = new URLSearchParams({ window: String(windowMonths) })
  if (customerId) qs.set("customer_id", customerId)
  if (division) qs.set("division", division)
  if (team) qs.set("team", team)
  if (origin) qs.set("origin", origin)
  if (dest) qs.set("dest", dest)
  appendScope(qs, scope)
  return useQuery({
    queryKey: ["savings", "monthly-totals", customerId, division, team, windowMonths, origin, dest, scopeKey(scope)],
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
  appendScope(qs, filters.scope)
  qs.set("page", String(filters.page ?? 1))
  qs.set("limit", String(filters.limit ?? 100))
  return useQuery({
    queryKey: ["savings", "lanes", filters],
    queryFn: () => apiFetch<SavingsLane[]>(`custom/carriers-savings/lanes?${qs}`),
  })
}

export interface SavingsLaneRate {
  avg_rate: number | null
  min_rate: number | null
  max_rate: number | null
  avg_rpm: number | null
  min_rpm: number | null
  max_rpm: number | null
  loads_included: number | null
  mileage: number | null
}

export interface SavingsLaneRates {
  sonar: SavingsLaneRate | null
  lb123: SavingsLaneRate | null
  skip_reason?: "non-us" | "unparseable"
}

/**
 * Per-lane SONAR + 123LB benchmark rates for the same set of lanes returned
 * by `useSavingsLanes`. Keyed by `${customer_id}|${origin_name}|${dest_name}`.
 * First call may be slow (cold cache); subsequent loads of the same month
 * are instant. Cross-border (non-US) lanes return `null` rates.
 */
export function useSavingsLaneRates(filters: SavingsLanesFilters) {
  const qs = new URLSearchParams()
  if (filters.month) qs.set("month", filters.month)
  if (filters.customerId) qs.set("customer_id", filters.customerId)
  if (filters.origin) qs.set("origin", filters.origin)
  if (filters.dest) qs.set("dest", filters.dest)
  if (filters.sort) qs.set("sort", filters.sort)
  if (filters.division) qs.set("division", filters.division)
  if (filters.team) qs.set("team", filters.team)
  appendScope(qs, filters.scope)
  qs.set("page", String(filters.page ?? 1))
  qs.set("limit", String(filters.limit ?? 100))
  return useQuery({
    queryKey: ["savings", "lane-rates", filters],
    queryFn: () =>
      apiFetch<Record<string, SavingsLaneRates>>(
        `custom/carriers-savings/lane-rates?${qs}`,
      ),
    // Closed months are immutable. The current MTD month soft-expires in 24h
    // server-side, so a 10-min client cache is safe everywhere.
    staleTime: 10 * 60 * 1000,
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
  pending_days: number
  holidays_days: number
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

export interface BudgetWeekPoint {
  week_start: string
  loads_actual: number
  loads_budget: number
  revenue_actual: number
  revenue_budget: number
  profit_actual: number
  profit_budget: number
}

export function useBudgetWeekly(filters: BudgetFilters) {
  // Weekly window is fixed (last 12 ISO weeks), so date filters are dropped —
  // only team / customer narrow the rollup.
  const rest: BudgetFilters = { teams: filters.teams, customer: filters.customer }
  return useQuery({
    queryKey: ["budget", "weekly", rest],
    queryFn: () =>
      apiFetch<BudgetWeekPoint[]>(`custom/budget-followup/weekly${budgetQs(rest)}`),
  })
}

export interface BudgetTop5Row {
  customer_name: string
  loads_var: number
  profit_var: number
  loads_actual: number
  loads_budget: number
  profit_actual: number
  profit_budget: number
}

export interface BudgetTop5 {
  top_volume: BudgetTop5Row[]
  worst_volume: BudgetTop5Row[]
  top_profit: BudgetTop5Row[]
  worst_profit: BudgetTop5Row[]
  non_budget: BudgetTop5Row[]
}

export function useBudgetTop5(filters: BudgetFilters) {
  return useQuery({
    queryKey: ["budget", "top5", filters],
    queryFn: () =>
      apiFetch<BudgetTop5>(`custom/budget-followup/top5${budgetQs(filters)}`),
  })
}

export interface BudgetMetricCell {
  actual: number
  budget: number
  var: number
  avg_last_month: number
  avg_week: number
  avg_day: number
  projected: number
}

export interface BudgetCustomerDetailRow {
  customer_name: string
  team_id: string
  revenue: BudgetMetricCell
  profit: BudgetMetricCell
  loads: BudgetMetricCell
}

export function useBudgetByCustomerDetail(filters: BudgetFilters) {
  return useQuery({
    queryKey: ["budget", "by-customer-detail", filters],
    queryFn: () =>
      apiFetch<BudgetCustomerDetailRow[]>(
        `custom/budget-followup/by-customer-detail${budgetQs(filters)}`,
      ),
  })
}

/**
 * Star / un-star a report. Writes `user_preferences.pinned_reports`, which is
 * what `GET /reports` reads back as `is_favorited` per row.
 *
 * Optimistic: the star and the favourites-first ordering are driven by cached
 * query data, so without this the whole grid would visibly re-sort a round-trip
 * after the click (and a Render cold start makes that seconds, not milliseconds).
 * `onSettled` re-fetches so the server stays the authority.
 */
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
    onMutate: async (reportId: string) => {
      await queryClient.cancelQueries({ queryKey: ["reports"] })
      await queryClient.cancelQueries({ queryKey: ["preferences"] })
      const prevReports = queryClient.getQueriesData({ queryKey: ["reports"] })
      const prevPrefs = queryClient.getQueryData(["preferences"])

      queryClient.setQueriesData(
        { queryKey: ["reports"] },
        (old: ApiResponse<Report[]> | undefined) =>
          !old?.data
            ? old
            : {
                ...old,
                data: old.data.map((r) =>
                  r.id === reportId ? { ...r, is_favorited: !r.is_favorited } : r,
                ),
              },
      )
      return { prevReports, prevPrefs }
    },
    onError: (error, _reportId, context) => {
      // Put the cache back exactly as it was before showing the toast.
      context?.prevReports?.forEach(([key, data]) => queryClient.setQueryData(key, data))
      if (context?.prevPrefs !== undefined) {
        queryClient.setQueryData(["preferences"], context.prevPrefs)
      }
      mutationErrorToast("Update favorite")(error)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["preferences"] })
      queryClient.invalidateQueries({ queryKey: ["reports"] })
    },
  })
}
