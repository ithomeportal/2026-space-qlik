"use client"

// Legend pills for the KPI MANAGEMENT chart (extracted from Chart.tsx).
//
// Two kinds on purpose:
//   * LegendChip  — a BUTTON: clicking it shows / hides its series.
//   * LegendLabel — a plain swatch + text, NOT interactive. Bruno PDF
//     2026-10-16 R1: "Variance" has no series of its own (it is a tooltip row,
//     Actual − Budget), so a clickable chip toggled nothing visible and read
//     as broken. It stays as a static label; the tooltip row stays too.

export function LegendChip({
  label,
  color,
  dashed,
  active,
  onClick,
}: {
  label: string
  color: string
  dashed?: boolean
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
        active
          ? "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F9FAFB]"
          : "border-[#E5E7EB] bg-[#F3F4F6] text-[#9CA3AF] line-through"
      }`}
    >
      <Swatch color={color} dashed={dashed} opacity={active ? 1 : 0.4} />
      {label}
    </button>
  )
}

export function LegendLabel({ label, color }: { label: string; color: string }) {
  return (
    <span className="flex cursor-default select-none items-center gap-1 px-2 py-0.5 text-[11px] text-[#374151]">
      <Swatch color={color} opacity={1} />
      {label}
    </span>
  )
}

function Swatch({ color, dashed, opacity }: { color: string; dashed?: boolean; opacity: number }) {
  return (
    <span
      className="inline-block h-2 w-4 rounded-sm"
      style={{
        background: dashed
          ? `repeating-linear-gradient(90deg, ${color} 0 4px, transparent 4px 8px)`
          : color,
        opacity,
      }}
    />
  )
}
