/**
 * Shared formatters for the Admin Aging Cashflow report.
 */
const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const USD_COMPACT = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
})
const COUNT = new Intl.NumberFormat("en-US")
const PCT2 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
})
const NUM1 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 0,
})

export const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : USD0.format(Number(v))

export const fmtUsdCompact = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : USD_COMPACT.format(Number(v))

export const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT.format(Number(v))

export const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT2.format(Number(v))}%`

export const fmtNum1 = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : NUM1.format(Number(v))

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  // Datalake stores everything in CST already; show MM/DD/YYYY without TZ shift.
  const d = iso.length >= 10 ? iso.slice(0, 10) : iso
  const [y, m, dd] = d.split("-")
  if (!y || !m || !dd) return iso
  return `${m}/${dd}/${y}`
}

/**
 * Color-band CSS classes for the aging "Days" column.
 *  green  ≤ threshold
 *  amber  threshold+1 .. threshold * 1.5
 *  red    > threshold * 1.5
 *  gray   null / negative
 */
export function daysBandClass(
  days: number | null | undefined,
  threshold: number,
): string {
  if (days === null || days === undefined) return "text-[#9CA3AF]"
  if (days < 0) return "text-[#9CA3AF] italic"
  if (days <= threshold) return "text-[#065F46] bg-[#ECFDF5]"
  if (days <= threshold * 1.5) return "text-[#92400E] bg-[#FEF3C7]"
  return "text-[#991B1B] bg-[#FEE2E2] font-semibold"
}
