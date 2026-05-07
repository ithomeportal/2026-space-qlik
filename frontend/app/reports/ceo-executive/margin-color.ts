// Bruno's tiered margin band (2026-05-07 feedback): green ≥ 17%,
// yellow ≥ 12% & < 17%, red < 12%. Applied to every Margin % column
// across the CEO Executive report so the eye picks up health at a glance.
// Caller passes margin in PERCENT (e.g. 16.1 for 16.1%), not the 0-1 decimal.

export function marginCellClass(marginPct: number | null | undefined): string {
  if (marginPct === null || marginPct === undefined || Number.isNaN(Number(marginPct))) {
    return ""
  }
  const m = Number(marginPct)
  if (m >= 17) return "bg-[#D1FAE5] text-[#065F46] font-semibold"
  if (m >= 12) return "bg-[#FEF3C7] text-[#92400E] font-semibold"
  return "bg-[#FEE2E2] text-[#991B1B] font-semibold"
}
