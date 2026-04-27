// Shared formatters for the Attrition WoW report. Centralized so every tab
// renders numbers identically (Bruno's PDF mixes thousands-separators and
// abbreviations; we normalize on en-US currency / count / 2-decimal pct).

export const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})

export const COUNT = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 0,
})

export const COUNT1 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
})

export const PCT2 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
})

export const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : USD0.format(Number(v))

export const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT.format(Number(v))

export const fmtCount1 = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT1.format(Number(v))

export const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT2.format(Number(v) * 100)}%`

export const fmtPctRaw = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT2.format(Number(v))}%`

export function fmtTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    })
  } catch {
    return iso
  }
}

export function fmtWeekRange(start: string, end: string): string {
  const s = new Date(start + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  })
  const e = new Date(end + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  })
  return `${s} – ${e}`
}

// Returns "+12.34%", "-5.67%", or "0.00%" depending on sign.
export function fmtSignedPct(v: number | null | undefined): {
  text: string
  className: string
} {
  if (v === null || v === undefined || Number.isNaN(Number(v))) {
    return { text: "—", className: "text-[#6B7280]" }
  }
  const n = Number(v)
  if (n > 0) {
    return { text: `+${PCT2.format(n * 100)}%`, className: "text-[#15803D]" }
  }
  if (n < 0) {
    return { text: `${PCT2.format(n * 100)}%`, className: "text-[#DC2626]" }
  }
  return { text: "0.00%", className: "text-[#B45309]" }
}

export function fmtSignedUsd(v: number | null | undefined): {
  text: string
  className: string
} {
  if (v === null || v === undefined || Number.isNaN(Number(v))) {
    return { text: "—", className: "text-[#6B7280]" }
  }
  const n = Number(v)
  if (n > 0) {
    return { text: `+${USD0.format(n)}`, className: "text-[#15803D]" }
  }
  if (n < 0) {
    return { text: USD0.format(n), className: "text-[#DC2626]" }
  }
  return { text: "$0", className: "text-[#B45309]" }
}

export function fmtSignedCount(v: number | null | undefined): {
  text: string
  className: string
} {
  if (v === null || v === undefined || Number.isNaN(Number(v))) {
    return { text: "—", className: "text-[#6B7280]" }
  }
  const n = Number(v)
  if (n > 0) {
    return { text: `+${COUNT.format(n)}`, className: "text-[#15803D]" }
  }
  if (n < 0) {
    return { text: COUNT.format(n), className: "text-[#DC2626]" }
  }
  return { text: "0", className: "text-[#B45309]" }
}
