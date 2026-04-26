export const COUNT = new Intl.NumberFormat("en-US")
export const PCT2 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
})

export const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : COUNT.format(Number(v))

export const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT2.format(Number(v))}%`

export function fmtTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}

export function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "2-digit",
      day: "2-digit",
      year: "2-digit",
    })
  } catch {
    return iso
  }
}

// Service-fail / on-time colour bands.
// On-time pct: <90% red, 90-94 amber, 95-98 teal, >=98 green.
export function onTimeColor(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || Number.isNaN(Number(pct)))
    return "text-[#6B7280]"
  if (pct < 90) return "text-[#DC2626]"
  if (pct < 95) return "text-[#B45309]"
  if (pct < 98) return "text-[#0F766E]"
  return "text-[#15803D]"
}

export function onTimeBg(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || Number.isNaN(Number(pct)))
    return "bg-[#F3F4F6]"
  if (pct < 90) return "bg-[#FEE2E2]"
  if (pct < 95) return "bg-[#FEF3C7]"
  if (pct < 98) return "bg-[#CCFBF1]"
  return "bg-[#DCFCE7]"
}

// Month bucket label "Apr - 26"
export function fmtMonthBucket(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    const d = new Date(iso + "T00:00:00")
    const mon = d.toLocaleDateString("en-US", { month: "short" })
    const yy = String(d.getFullYear() % 100).padStart(2, "0")
    return `${mon} - ${yy}`
  } catch {
    return iso
  }
}
