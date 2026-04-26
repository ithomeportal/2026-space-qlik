export const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
export const COUNT = new Intl.NumberFormat("en-US")
export const PCT2 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
})

export const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))

export const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT.format(Number(v))

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

export function marginColor(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || Number.isNaN(Number(pct)))
    return "text-[#6B7280]"
  if (pct < 0) return "text-[#DC2626]"
  if (pct < 10) return "text-[#B45309]"
  if (pct < 20) return "text-[#0F766E]"
  return "text-[#15803D]"
}

export function marginBgColor(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || Number.isNaN(Number(pct)))
    return "bg-[#F3F4F6]"
  if (pct < 0) return "bg-[#FEE2E2]"
  if (pct < 10) return "bg-[#FEF3C7]"
  if (pct < 20) return "bg-[#CCFBF1]"
  return "bg-[#DCFCE7]"
}
