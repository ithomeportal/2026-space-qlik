"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: {
    total?: number
    page?: number
    limit?: number
  }
}

async function apiFetch<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const RETRY_OPTS = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Filter contract
// ---------------------------------------------------------------------------

export type ItTicketsRange =
  | "today"
  | "wtd"
  | "last_7d"
  | "last_30d"
  | "mtd"
  | "last_month"
  | "ytd"
  | "custom"

export type ItTicketsType = "service_request" | "incident"

export interface ItTicketsFilters {
  range: ItTicketsRange
  startDate?: string // YYYY-MM-DD (only used when range === 'custom')
  endDate?: string
  type: ItTicketsType
}

function ttQs(
  f: ItTicketsFilters,
  extra?: Record<string, string>,
): string {
  const q = new URLSearchParams()
  q.set("range", f.range)
  q.set("type", f.type)
  if (f.range === "custom" && f.startDate) q.set("start", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end", f.endDate)
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ItTicketsKpis {
  pending_now: number
  closed: number
  total: number
  pct_open: number
  pct_closed: number
}

export interface ItByMonthRow {
  month_start: string
  month_label: string
  category: string
  cnt: number
}

export interface ItStatusRow {
  status: string
  cnt: number
}

export interface ItPriorityRow {
  priority: string
  cnt: number
}

export interface ItByWeekRow {
  week_start: string
  category: string
  cnt: number
}

export interface ItByDayRow {
  day: string
  category: string
  cnt: number
}

export interface ItAgentRow {
  agent: string
  cnt: number
}

export interface ItHistoryStatusRow {
  day: string
  status: string
  cnt: number
}

export interface ItHistoryCategoryRow {
  category: string
  cnt: number
}

export interface ItTicketsSummary {
  type: string
  range: { start: string; end: string }
  kpis: ItTicketsKpis
  by_month: ItByMonthRow[]
  status: ItStatusRow[]
  priority: ItPriorityRow[]
  by_week_pending: ItByWeekRow[]
  by_day_pending: ItByDayRow[]
  by_agent: ItAgentRow[]
  history_status: ItHistoryStatusRow[]
  history_category: ItHistoryCategoryRow[]
}

export interface ItTicketRow {
  id: number
  created: string | null
  category: string | null
  sub_category: string | null
  item_category: string | null
  agent: string | null
  name: string | null
  subject: string | null
  status: string | null
  due_by: string | null
  updated: string | null
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useItTicketsSummary(f: ItTicketsFilters) {
  return useQuery({
    ...RETRY_OPTS,
    queryKey: ["it-tickets", "summary", f],
    queryFn: () =>
      apiFetch<ItTicketsSummary>(`custom/it-tickets/summary${ttQs(f)}`),
  })
}

export function useItTicketsTable(
  f: ItTicketsFilters,
  which: "pending" | "closed",
  page: number,
  pageSize: number,
  sort: string | null,
) {
  return useQuery({
    ...RETRY_OPTS,
    queryKey: ["it-tickets", which, f, page, pageSize, sort],
    queryFn: () =>
      apiFetch<ItTicketRow[]>(
        `custom/it-tickets/${which}${ttQs(f, {
          page: String(page),
          page_size: String(pageSize),
          ...(sort ? { sort } : {}),
        })}`,
      ),
  })
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

export function fmtInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "0"
  return Math.round(n).toLocaleString("en-US")
}

export function fmtPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "0%"
  return `${n.toFixed(1)}%`
}

export function fmtDateTime(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function fmtIsoDay(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
}

// Aging band — used to color pending rows. Returns Tailwind bg classes.
export function agingBand(createdIso: string | null): {
  days: number
  cls: string
  label: string
} {
  if (!createdIso) {
    return { days: 0, cls: "", label: "" }
  }
  const created = new Date(createdIso).getTime()
  if (Number.isNaN(created)) return { days: 0, cls: "", label: "" }
  const days = Math.floor((Date.now() - created) / (1000 * 60 * 60 * 24))
  if (days <= 3) {
    return { days, cls: "bg-emerald-50", label: `${days}d` }
  }
  if (days <= 7) {
    return { days, cls: "bg-amber-50", label: `${days}d` }
  }
  if (days <= 14) {
    return { days, cls: "bg-orange-50", label: `${days}d` }
  }
  return { days, cls: "bg-rose-100", label: `${days}d` }
}
