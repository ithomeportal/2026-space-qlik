/**
 * Shared formatters + color logic for the Carrier SMS Score report.
 * Mirrors the AP app's safety-performance-card.tsx / mcp-risk-card.tsx
 * thresholds so the portal table reads the same as the per-carrier view.
 */
const COUNT = new Intl.NumberFormat("en-US")
const PCT1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1, minimumFractionDigits: 1 })

export const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : COUNT.format(Number(v))

export const fmtPct1 = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT1.format(Number(v))}%`

export const fmtMeasure = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : PCT1.format(Number(v))

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = iso.length >= 10 ? iso.slice(0, 10) : iso
  const [y, m, dd] = d.split("-")
  if (!y || !m || !dd) return iso
  return `${m}/${dd}/${y}`
}

// ---- Color helpers ---------------------------------------------------------

/** OOS rate cell: red when above the national average, green at/below, neutral when unknown. */
export function oosClass(value: number | null, natAvg: number): string {
  if (value === null || Number.isNaN(value)) return "text-[#9CA3AF]"
  return value > natAvg ? "text-[#B91C1C] font-semibold" : "text-[#15803D]"
}

/** BASIC measure badge classes — green/amber/red at 50/75 (higher = more concern). */
export function basicBadgeClass(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "bg-[#F3F4F6] text-[#9CA3AF]"
  if (value >= 75) return "bg-[#FEE2E2] text-[#B91C1C]"
  if (value >= 50) return "bg-[#FEF3C7] text-[#B45309]"
  return "bg-[#DCFCE7] text-[#15803D]"
}

/** MCP risk verdict badge — success when "Acceptable", destructive otherwise. */
export function mcpBadgeClass(risk: string | null): string {
  if (!risk) return "bg-[#F3F4F6] text-[#9CA3AF]"
  return risk.toLowerCase() === "acceptable"
    ? "bg-[#DCFCE7] text-[#15803D]"
    : "bg-[#FEE2E2] text-[#B91C1C]"
}
