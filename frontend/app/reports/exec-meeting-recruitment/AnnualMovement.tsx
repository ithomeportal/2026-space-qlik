"use client"

import { ArrowDownRight, ArrowUpRight, Info, UserMinus, UserPlus } from "lucide-react"
import { Section, Segmented } from "./Section"
import { fmtKpi, fmtPct, type EmrAnnual } from "@/lib/exec-meeting-recruitment-api"

/**
 * Request 5 — "02 · ANNUAL MOVEMENT".
 *
 * The New-hires caption is load-bearing, not decoration. New hires come from
 * the time-off "hireDate" column (the definition the Jobs portal uses), and
 * that table drops departed staff over time, so prior years are undercounts —
 * 2024 held only ~25% of the people actually onboarded when measured against
 * FreshService tickets. Without the caption the rising series reads as a
 * hiring trend when it is mostly improving coverage.
 */
export function AnnualMovement({
  data,
  loading,
  years,
  year,
  onYear,
}: {
  data?: EmrAnnual
  loading: boolean
  years: number[]
  year: number
  onYear: (next: number) => void
}) {
  const turnover = data?.turnover_rate ?? null

  return (
    <Section
      index="02"
      eyebrow="Annual movement"
      title="New hires & offboarding"
      subtitle="Choose a year to view people entering and leaving the organization."
      actions={
        <>
          <div
            className="flex items-center gap-2 rounded-lg border border-[#E5E7EB] bg-white px-3 py-2"
            title={
              data?.turnover_basis
                ? `Turnover = ${data.turnover_basis}. Shown for the current year only: headcount during a past year cannot be reconstructed from the time-off table, so a prior-year rate would be invented rather than measured.`
                : "Turnover is shown for the current year only — headcount during a past year cannot be reconstructed from the time-off table."
            }
          >
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[#9CA3AF]">
              Turnover rate
            </span>
            <span className="font-serif text-xl font-semibold tabular-nums text-[#111827]">
              {fmtPct(turnover)}
            </span>
            <span className="text-[10px] text-[#9CA3AF]">
              {turnover === null ? "current year only" : `in ${data?.year}`}
            </span>
          </div>
          <Segmented
            label="View year"
            options={years.map((y) => ({ k: y, label: String(y) }))}
            value={year}
            onChange={onYear}
          />
        </>
      }
    >
      {loading && !data ? (
        <div className="grid gap-4 md:grid-cols-2">
          {[0, 1].map((i) => (
            <div key={i} className="h-[92px] animate-pulse rounded-xl bg-[#F3F4F6]" />
          ))}
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <MovementCard
              icon={<UserPlus className="h-4 w-4" />}
              label="New hires"
              caption={`Joined in ${data?.year ?? year}`}
              value={data?.new_hires}
              accent="#0F766E"
              trailing={<ArrowUpRight className="h-4 w-4 text-[#0F766E]" />}
            />
            <MovementCard
              icon={<UserMinus className="h-4 w-4" />}
              label="Offboarding"
              caption={`Exited in ${data?.year ?? year}`}
              value={data?.offboarding}
              accent="#B45309"
              trailing={<ArrowDownRight className="h-4 w-4 text-[#B45309]" />}
            />
          </div>

          <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-relaxed text-[#6B7280]">
            <Info className="mt-0.5 h-3 w-3 shrink-0 text-[#9CA3AF]" />
            <span>
              New hires come from time-off hire dates; offboarding from FreshService
              Offboarding tickets.{" "}
              {data?.hires_are_historical ? (
                <strong className="font-semibold text-[#92400E]">
                  Earlier years undercount new hires — people who have since left drop out
                  of the time-off system, so {data?.year} is not directly comparable to the
                  current year.
                </strong>
              ) : (
                "The two come from different systems, so they are counts of the same period rather than a matched in/out pair."
              )}
            </span>
          </p>
        </>
      )}
    </Section>
  )
}

function MovementCard({
  icon,
  label,
  caption,
  value,
  accent,
  trailing,
}: {
  icon: React.ReactNode
  label: string
  caption: string
  value?: number
  accent: string
  trailing: React.ReactNode
}) {
  return (
    <div
      className="flex items-center justify-between rounded-xl border-t-2 border-[#E5E7EB] bg-[#F9FAFB] p-4"
      style={{ borderTopColor: accent }}
    >
      <div className="flex items-center gap-3">
        <span className="rounded-lg bg-white p-2 text-[#6B7280] shadow-sm">{icon}</span>
        <div>
          <div className="text-xs font-semibold text-[#374151]">{label}</div>
          <div className="text-[11px] text-[#9CA3AF]">{caption}</div>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span className="font-serif text-3xl font-semibold tabular-nums text-[#111827]">
          {fmtKpi(value)}
        </span>
        {trailing}
      </div>
    </div>
  )
}
