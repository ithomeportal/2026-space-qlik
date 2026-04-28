export function fmtInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—"
  return Math.round(n).toLocaleString("en-US")
}

/** Plain integer with no rounding — used for count-style metrics where
 * the underlying value is already integer (offer lanes, lane counts). */
export function fmtCount(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—"
  return Math.round(n).toLocaleString("en-US")
}

export function fmtMoney(
  n: number | null | undefined,
  opts: { compact?: boolean } = {},
): string {
  if (n == null || Number.isNaN(n)) return "—"
  if (opts.compact) {
    const abs = Math.abs(n)
    const sign = n < 0 ? "-" : ""
    if (abs >= 1_000_000_000) return `${sign}$${(abs / 1_000_000_000).toFixed(2)}B`
    if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`
    if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`
    return `${sign}$${abs.toFixed(0)}`
  }
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })
}

export function fmtPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—"
  return `${(n * 100).toFixed(2)}%`
}

export function fmtMonth(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso + "T00:00:00")
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" })
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso + "T00:00:00")
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString("en-US", {
    month: "numeric",
    day: "numeric",
    year: "2-digit",
  })
}

/** RFP status pill colour — matches Bruno's Qlik chips. */
export function statusPillClass(status: string | null | undefined): string {
  const s = (status ?? "").toLowerCase()
  if (s === "won") return "bg-[#D1FAE5] text-[#065F46]"
  if (s === "lost") return "bg-[#FEE2E2] text-[#991B1B]"
  if (s.startsWith("pending final")) return "bg-[#FFEDD5] text-[#9A3412]"
  if (s.startsWith("pending bid")) return "bg-[#FEF3C7] text-[#92400E]"
  if (s.startsWith("quoting")) return "bg-[#FEF3C7] text-[#92400E]"
  if (s.startsWith("round")) return "bg-[#DBEAFE] text-[#1E40AF]"
  return "bg-[#F3F4F6] text-[#6B7280]"
}

/** Days-to-end-of-RFP colour band. */
export function daysToEndClass(d: number | null | undefined): string {
  if (d == null) return "bg-[#F3F4F6] text-[#6B7280]"
  if (d < 0) return "bg-[#FEE2E2] text-[#991B1B]"
  if (d <= 30) return "bg-[#FEE2E2] text-[#991B1B]"
  if (d <= 90) return "bg-[#FEF3C7] text-[#92400E]"
  return "bg-[#D1FAE5] text-[#065F46]"
}

export function daysBetween(iso: string | null | undefined): number | null {
  if (!iso) return null
  const d = new Date(iso + "T00:00:00")
  if (Number.isNaN(d.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const ms = d.getTime() - today.getTime()
  return Math.round(ms / 86400000)
}
