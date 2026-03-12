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
  qlik_app_id: string
  qlik_sheet_id: string | null
  title: string
  description: string | null
  category: string | null
  tags: string[]
  owner_name: string | null
  data_sources: string[]
  last_reload: string | null
  is_active: boolean
  is_favorited?: boolean
}

export function useReports(category?: string) {
  return useQuery({
    queryKey: ["reports", category],
    queryFn: () => apiFetch<Report[]>(`reports${category ? `?category=${category}` : ""}`),
  })
}

export function useReport(id: string) {
  return useQuery({
    queryKey: ["report", id],
    queryFn: () => apiFetch<Report>(`reports/${id}`),
    enabled: !!id,
  })
}

export function useTrending() {
  return useQuery({
    queryKey: ["trending"],
    queryFn: () => apiFetch<Report[]>("reports/trending"),
  })
}

export function useSearchReports(query: string) {
  return useQuery({
    queryKey: ["search", query],
    queryFn: () => apiFetch<Report[]>(`reports/search?q=${encodeURIComponent(query)}`),
    enabled: query.length > 0,
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
