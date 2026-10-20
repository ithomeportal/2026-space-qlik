"use client"

import { keepPreviousData, useQuery } from "@tanstack/react-query"

// Customer E-mail Activity — reads /api/custom/customer-status-email/activity.
// Backend: backend/app/routers/customer_status_email.py

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
}

export const API_BASE = "custom/customer-status-email"

async function apiFetch<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

export type SendStatus = "sent" | "failed" | "sending" | "skipped"
export type SlotStatus = SendStatus | "missed" | "upcoming" | "not_live"

export interface Recipients {
  from: string
  to: string[]
  cc: string[]
  bcc: string[]
}

export interface BucketCounts {
  in_progress: number
  scheduled: number
  delivered: number
}

export interface ActivityRow {
  report_key: string
  slot_key: string
  mode: "test" | "live" | "manual"
  status: SendStatus
  counts: BucketCounts | null
  subject: string | null
  recipients: Recipients | null
  loads: Record<keyof BucketCounts, string[]> | null
  error: string | null
  claimed_at: string
  finished_at: string | null
}

export interface TodaySlot {
  hour: number
  status: SlotStatus
  sentAt: string | null
}

export interface TodayReport {
  key: string
  subject: string
  slots: TodaySlot[]
}

export interface ActivityData {
  rows: ActivityRow[]
  today: TodayReport[]
  live: boolean
  enabled: boolean
  now: string
}

export function useCustomerEmailActivity(days: number, report: string | null) {
  const qs = new URLSearchParams({ days: String(days) })
  if (report) qs.set("report", report)
  return useQuery({
    queryKey: ["customer-status-email", "activity", days, report],
    queryFn: async () => {
      const res = await apiFetch<ActivityData>(`${API_BASE}/activity?${qs.toString()}`)
      if (!res.success || !res.data) throw new Error(res.error ?? "Failed to load activity")
      return res.data
    },
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
    ...RETRY,
  })
}

export function previewUrl(key: string): string {
  return `/api/proxy/${API_BASE}/${key}/preview`
}
