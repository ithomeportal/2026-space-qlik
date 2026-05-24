// Shared formatters + brand palette for the Bonus Calculator report.
// Colors are taken verbatim from Bruno's PDF spec (RGB values).

export const BRAND = "rgb(86,17,149)" // #561195 — header / accents
export const BRAND_DARK = "rgb(66,10,120)"

export const COLORS = {
  loadHeader: "rgb(98,116,142)",
  marginHeader: "rgb(255,184,106)",
  serviceHeader: "rgb(255,210,48)",
  cardBg: "rgb(245,243,255)",
  cardTitle: "rgb(142,109,255)",
  wildcardBg: "rgb(236,253,245)",
  wildcardTitle: "rgb(4,163,161)",
  greenRow: "rgb(220,252,80)",
  blueHeader: "rgb(43,108,176)",
}

export function usd(n: number | null | undefined, dp = 2): string {
  if (n == null || !isFinite(n)) return "—"
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: dp, maximumFractionDigits: dp })
}

export function usd0(n: number | null | undefined): string {
  return usd(n, 0)
}

export function pct(n: number | null | undefined, dp = 2): string {
  if (n == null || !isFinite(n)) return "—"
  return `${n.toFixed(dp)}%`
}

export function num(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "—"
  return Math.round(n).toLocaleString("en-US")
}

export const ROLE_LABEL: Record<string, string> = {
  kam: "KAM",
  freight_match: "Freight Match",
  tracking_tracing: "Tracking & Tracing",
}
