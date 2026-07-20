const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const COUNT = new Intl.NumberFormat("en-US")

export const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : USD0.format(Number(v))

export const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : COUNT.format(Number(v))

/** Loss cell — blank when zero so the pivot reads cleanly. */
export const fmtLossCell = (v: number | null | undefined) =>
  v === null || v === undefined || Number(v) === 0 || Number.isNaN(Number(v))
    ? "—"
    : USD0.format(Number(v))
