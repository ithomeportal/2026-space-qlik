export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  // accept both YYYY-MM-DD and full ISO
  const d = iso.length === 10 ? new Date(iso + "T12:00:00") : new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

export function fmtCount(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  return Math.round(n).toLocaleString()
}

export function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  if (Math.abs(n) >= 1_000_000) {
    return `$${(n / 1_000_000).toFixed(2)}M`
  }
  if (Math.abs(n) >= 10_000) {
    return `$${(n / 1_000).toFixed(1)}K`
  }
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  })
}

export function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  return `${n.toFixed(2)}%`
}
