export function fmtInt(n: number | null | undefined): string {
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
    if (abs >= 1_000_000) return `${n < 0 ? "-" : ""}$${(abs / 1_000_000).toFixed(2)}M`
    if (abs >= 1_000) return `${n < 0 ? "-" : ""}$${(abs / 1_000).toFixed(1)}k`
    return `${n < 0 ? "-" : ""}$${abs.toFixed(0)}`
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

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso + "T00:00:00")
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString("en-US", {
    month: "numeric",
    day: "numeric",
    year: "numeric",
  })
}
