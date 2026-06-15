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
  budget?: {
    applicable: boolean
    loads?: number
    revenue?: number
    profit?: number
  }
}

// "Bgt $X · NN% attained" sub-line for the actual-vs-budget KPI cards (CORP only).
function budgetSub(
  actual: number | null | undefined,
  goal: number | undefined,
  formatter: (n: number) => string,
): { text: string; tone: "up" | "down" | "neutral" } | null {
  if (goal === undefined || goal === null || goal === 0) return null
  const a = Number(actual ?? 0)
  const pct = (a / goal) * 100
  const tone = pct >= 100 ? "up" : pct >= 80 ? "neutral" : "down"
  return { text: `Bgt ${formatter(goal)} · ${pct.toFixed(0)}%`, tone }
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

  const bdg = !isDelta && values?.budget?.applicable ? values.budget : undefined
  const cards: Array<{
    key: string
    label: string
    value: string
    dot?: "up" | "down" | "neutral"
    sub?: { text: string; tone: "up" | "down" | "neutral" } | null
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
        {
          key: "rev",
          label: "$Revenue",
          value: fmtUsd(values?.revenue),
          sub: budgetSub(values?.revenue, bdg?.revenue, (n) => fmtUsd(n)),
        },
        {
          key: "prof",
          label: "$Profit",
          value: fmtUsd(values?.profit),
          sub: budgetSub(values?.profit, bdg?.profit, (n) => fmtUsd(n)),
        },
        { key: "mar", label: "% Margin", value: fmtPct(values?.margin_pct) },
        {
          key: "loads",
          label: "# Loads",
          value: fmtCount(values?.loads),
          sub: budgetSub(values?.loads, bdg?.loads, (n) => fmtCount(n)),
        },
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
            {c.sub && (
              <div
                className={`mt-0.5 text-[10px] font-medium tabular-nums ${
                  c.sub.tone === "up"
                    ? "text-[#16A34A]"
                    : c.sub.tone === "down"
                      ? "text-[#DC2626]"
                      : "text-[#92400E]"
                }`}
              >
                {c.sub.text}
              </div>
            )}
          </div>
        ))}
      </div>
      {!isDelta && values?.budget?.applicable && (
        <div className="mt-2 text-[10px] text-[#9CA3AF]">
          Bgt = CORP budget goal for this window · % = actual ÷ budget
        </div>
      )}
    </div>
  )
}
