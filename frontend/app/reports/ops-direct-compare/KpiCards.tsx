"use client"

import { fmtCount, fmtPct, fmtUsd } from "../ops-margins/format"

type Variant = "p1" | "p2" | "delta"

interface KpiValues {
  loads: number | null | undefined
  revenue: number | null | undefined
  profit: number | null | undefined
  margin_pct: number | null | undefined
  avg_r_per_l: number | null | undefined
  avg_p_per_l: number | null | undefined
}

interface Props {
  variant: Variant
  values: KpiValues | null
  loading?: boolean
}

const ACCENT_TONES = {
  p1: { ring: "border-[#BFDBFE]", chip: "bg-[#DBEAFE] text-[#1E40AF]", title: "Panel 1" },
  p2: { ring: "border-[#DDD6FE]", chip: "bg-[#EDE9FE] text-[#5B21B6]", title: "Panel 2" },
  delta: {
    ring: "border-[#FCD34D]",
    chip: "bg-[#FEF3C7] text-[#92400E]",
    title: "Δ Panel 1 − Panel 2",
  },
}

function deltaSign(v: number | null | undefined, betterWhen: "higher" | "lower" = "higher") {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "neutral"
  if (v === 0) return "neutral"
  const positive = Number(v) > 0
  if (betterWhen === "higher") return positive ? "up" : "down"
  return positive ? "down" : "up"
}

function Dot({ tone }: { tone: "up" | "down" | "neutral" }) {
  const cls =
    tone === "up"
      ? "bg-[#16A34A]"
      : tone === "down"
        ? "bg-[#DC2626]"
        : "bg-[#9CA3AF]"
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${cls}`} />
}

function fmtSigned(
  v: number | null | undefined,
  formatter: (n: number) => string,
): string {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—"
  const n = Number(v)
  const sign = n > 0 ? "+" : n < 0 ? "−" : ""
  return `${sign}${formatter(Math.abs(n))}`
}

export function KpiCards({ variant, values, loading }: Props) {
  const tone = ACCENT_TONES[variant]
  const isDelta = variant === "delta"

  const cards: Array<{
    key: string
    label: string
    value: string
    dot?: "up" | "down" | "neutral"
  }> = isDelta
    ? [
        {
          key: "rev",
          label: "$Revenue",
          value: fmtSigned(values?.revenue, (n) => fmtUsd(n)),
          dot: deltaSign(values?.revenue),
        },
        {
          key: "prof",
          label: "$Profit",
          value: fmtSigned(values?.profit, (n) => fmtUsd(n)),
          dot: deltaSign(values?.profit),
        },
        {
          key: "mar",
          label: "% Margin",
          value:
            values?.margin_pct === null || values?.margin_pct === undefined
              ? "—"
              : fmtSigned(values.margin_pct, (n) => `${n.toFixed(2)}%`),
          dot: deltaSign(values?.margin_pct),
        },
        {
          key: "loads",
          label: "# Loads",
          value: fmtSigned(values?.loads, (n) => fmtCount(n)),
          dot: deltaSign(values?.loads),
        },
        {
          key: "avgr",
          label: "Avg $R / #L",
          value: fmtSigned(values?.avg_r_per_l, (n) => fmtUsd(n)),
          dot: deltaSign(values?.avg_r_per_l),
        },
        {
          key: "avgp",
          label: "Avg $P / #L",
          value: fmtSigned(values?.avg_p_per_l, (n) => fmtUsd(n)),
          dot: deltaSign(values?.avg_p_per_l),
        },
      ]
    : [
        { key: "rev", label: "$Revenue", value: fmtUsd(values?.revenue) },
        { key: "prof", label: "$Profit", value: fmtUsd(values?.profit) },
        { key: "mar", label: "% Margin", value: fmtPct(values?.margin_pct) },
        { key: "loads", label: "# Loads", value: fmtCount(values?.loads) },
        { key: "avgr", label: "Avg $R / #L", value: fmtUsd(values?.avg_r_per_l) },
        { key: "avgp", label: "Avg $P / #L", value: fmtUsd(values?.avg_p_per_l) },
      ]

  return (
    <div className={`rounded-xl border ${tone.ring} bg-white p-3 shadow-sm`}>
      <div className="mb-2 flex items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${tone.chip}`}>
          {tone.title}
        </span>
        {loading && <span className="text-[10px] text-[#9CA3AF]">loading…</span>}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {cards.map((c) => (
          <div
            key={c.key}
            className="rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2"
          >
            <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-[#6B7280]">
              {c.label}
              {isDelta && c.dot && <Dot tone={c.dot} />}
            </div>
            <div className="mt-1 text-lg font-semibold tabular-nums text-[#111827]">
              {c.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
