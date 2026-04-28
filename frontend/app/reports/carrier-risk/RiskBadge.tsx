"use client"

import type { RiskBand } from "@/lib/carrier-risk-api"

const STYLES: Record<RiskBand, { bg: string; fg: string; label: string }> = {
  red: { bg: "#FEE2E2", fg: "#991B1B", label: "Single carrier" },
  amber: { bg: "#FEF3C7", fg: "#92400E", label: "Concentrated" },
  green: { bg: "#DCFCE7", fg: "#166534", label: "Diversified" },
}

export function RiskBadge({ band }: { band: RiskBand }) {
  const s = STYLES[band]
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium"
      style={{ backgroundColor: s.bg, color: s.fg }}
      title={
        band === "red"
          ? "Lane has only one carrier and ≥ 5 movements — capacity risk if that carrier drops."
          : band === "amber"
            ? "Top carrier handles ≥ 70% of lane volume on a high-traffic lane (≥ 10 movements)."
            : "Diverse carrier mix on this lane."
      }
    >
      <span
        className="mr-1 inline-block h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: s.fg }}
      />
      {s.label}
    </span>
  )
}
