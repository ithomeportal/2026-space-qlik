import type { SlotStatus } from "@/lib/customer-status-email-api"

const STYLES: Record<SlotStatus, { label: string; cls: string }> = {
  sent: { label: "Sent", cls: "bg-green-100 text-green-800 border-green-300" },
  failed: { label: "Failed", cls: "bg-red-100 text-red-800 border-red-300" },
  sending: { label: "Sending", cls: "bg-amber-100 text-amber-800 border-amber-300" },
  skipped: { label: "Skipped · no loads", cls: "bg-slate-100 text-slate-600 border-slate-300" },
  missed: { label: "Missed", cls: "bg-red-50 text-red-700 border-red-300 border-dashed" },
  upcoming: { label: "Upcoming", cls: "bg-slate-50 text-slate-500 border-slate-200" },
  not_live: { label: "Not live yet", cls: "bg-white text-slate-400 border-slate-200" },
}

export function StatusBadge({ status }: { status: SlotStatus }) {
  const s = STYLES[status] ?? STYLES.upcoming
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-[11px] font-medium ${s.cls}`}>
      {s.label}
    </span>
  )
}

/** "2026-10-20T16:00:04" (already CST) → "10/20 04:00 PM" — string maths, never new Date(). */
export function fmtCst(ts: string | null): string {
  if (!ts) return "—"
  const [date, time] = ts.split("T")
  const [, m, d] = date.split("-")
  const [hh, mm] = time.split(":")
  const h = Number(hh)
  const h12 = h % 12 === 0 ? 12 : h % 12
  return `${m}/${d} ${String(h12).padStart(2, "0")}:${mm} ${h < 12 ? "AM" : "PM"}`
}

export function fmtHour(hour: number): string {
  const h12 = hour % 12 === 0 ? 12 : hour % 12
  return `${h12}:00 ${hour < 12 ? "AM" : "PM"}`
}
