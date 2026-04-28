/**
 * Shared formatters for the Carrier Risk report. Kept tiny so the page
 * and table components don't each re-create their own Intl instances.
 */
const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const COUNT = new Intl.NumberFormat("en-US")
const PCT2 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
})
const NUM2 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 0,
})

export const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : USD0.format(Number(v))

export const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT.format(Number(v))

export const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT2.format(Number(v))}%`

export const fmtNum = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : NUM2.format(Number(v))

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  // Datalake stores everything in CST already; show MM/DD/YYYY without TZ shift.
  const d = iso.length >= 10 ? iso.slice(0, 10) : iso
  const [y, m, dd] = d.split("-")
  if (!y || !m || !dd) return iso
  return `${m}/${dd}/${y}`
}
