"use client"

import { useMemo } from "react"
import Link from "next/link"
import { ArrowLeft, Lock, RefreshCw, ChevronRight } from "lucide-react"
import { ReportGuard } from "@/components/ReportGuard"
import {
  useCockpitSummary,
  fmtValue,
  fmtDelta,
  fmtAsOf,
  fmtGeneratedAt,
  type CockpitTile,
  type CockpitLinkTile,
  type TileStatus,
} from "@/lib/ceo-cockpit-api"

const STATUS_STYLES: Record<
  TileStatus,
  { ring: string; chip: string; chipText: string; dot: string; value: string }
> = {
  good: { ring: "#BBF7D0", chip: "#F0FDF4", chipText: "#15803D", dot: "#16A34A", value: "#111827" },
  warn: { ring: "#FDE68A", chip: "#FFFBEB", chipText: "#B45309", dot: "#D97706", value: "#111827" },
  bad: { ring: "#FECACA", chip: "#FEF2F2", chipText: "#B91C1C", dot: "#DC2626", value: "#111827" },
  neutral: { ring: "#E5E7EB", chip: "#F8FAFC", chipText: "#475569", dot: "#94A3B8", value: "#111827" },
  unavailable: { ring: "#E5E7EB", chip: "#F8FAFC", chipText: "#9CA3AF", dot: "#D1D5DB", value: "#9CA3AF" },
  locked: { ring: "#E5E7EB", chip: "#F8FAFC", chipText: "#9CA3AF", dot: "#D1D5DB", value: "#9CA3AF" },
}

const STATUS_LABEL: Record<TileStatus, string> = {
  good: "On track",
  warn: "Watch",
  bad: "Attention",
  neutral: "Info",
  unavailable: "No data",
  locked: "No access",
}

function KpiTile({ tile }: { tile: CockpitTile }) {
  const s = STATUS_STYLES[tile.status]
  const delta = fmtDelta(tile.delta_pct)
  const asOf = fmtAsOf(tile.as_of)
  const isDim = tile.status === "unavailable" || tile.status === "locked"

  return (
    <Link href={tile.deeplink} className="group block">
      <div
        className="flex h-full flex-col rounded-xl border bg-white p-4 shadow-sm transition hover:shadow-md"
        style={{ borderColor: s.ring }}
      >
        <div className="flex items-start justify-between gap-2">
          <span className="text-[13px] font-semibold leading-tight text-[#1B3A5C]">
            {tile.title}
          </span>
          <span
            className="flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold"
            style={{ background: s.chip, color: s.chipText }}
          >
            {tile.status === "locked" && <Lock className="h-3 w-3" />}
            {!isDim && (
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: s.dot }} />
            )}
            {STATUS_LABEL[tile.status]}
          </span>
        </div>

        <div className="mt-1 text-[11px] uppercase tracking-wider text-[#9CA3AF]">
          {tile.label}
        </div>

        <div className="mt-2 flex items-end gap-2">
          <span className="text-2xl font-semibold tabular-nums" style={{ color: s.value }}>
            {fmtValue(tile.value, tile.unit)}
          </span>
          {delta && (
            <span
              className="pb-1 text-xs font-semibold tabular-nums"
              style={{ color: s.chipText }}
            >
              {delta}
            </span>
          )}
        </div>

        {tile.desc && (
          <p className="mt-2 text-[10px] leading-snug text-[#9CA3AF]">{tile.desc}</p>
        )}

        <div className="mt-auto flex items-center justify-between pt-3 text-[10px] text-[#9CA3AF]">
          <span>{asOf ? `as of ${asOf}` : " "}</span>
          <span className="flex items-center gap-0.5 text-[#6B7280] opacity-0 transition group-hover:opacity-100">
            Open <ChevronRight className="h-3 w-3" />
          </span>
        </div>
      </div>
    </Link>
  )
}

function LinkTile({ tile }: { tile: CockpitLinkTile }) {
  return (
    <Link href={tile.deeplink} className="group block">
      <div className="flex h-full flex-col rounded-xl border border-dashed border-[#E5E7EB] bg-[#FAFAFA] p-4 transition hover:border-[#CBD5E1] hover:bg-white">
        <div className="flex items-start justify-between gap-2">
          <span className="text-[13px] font-semibold leading-tight text-[#475569]">
            {tile.title}
          </span>
          <ChevronRight className="h-4 w-4 shrink-0 text-[#9CA3AF] transition group-hover:translate-x-0.5" />
        </div>
        {tile.note && (
          <div className="mt-2 text-[11px] leading-snug text-[#9CA3AF]">{tile.note}</div>
        )}
      </div>
    </Link>
  )
}

function TileSkeleton() {
  return (
    <div className="h-[150px] animate-pulse rounded-xl border border-[#E5E7EB] bg-white p-4">
      <div className="h-3 w-2/3 rounded bg-[#F1F5F9]" />
      <div className="mt-4 h-6 w-1/2 rounded bg-[#F1F5F9]" />
      <div className="mt-6 h-2 w-1/3 rounded bg-[#F1F5F9]" />
    </div>
  )
}

function CockpitContent() {
  const { data, isLoading, isError, isFetching, refetch } = useCockpitSummary()
  const cockpit = data?.data

  const grouped = useMemo(() => {
    if (!cockpit) return []
    const order = cockpit.category_order ?? []
    const cats = new Set<string>([
      ...order,
      ...cockpit.tiles.map((t) => t.category),
      ...cockpit.link_tiles.map((t) => t.category),
    ])
    const ordered = [
      ...order.filter((c) => cats.has(c)),
      ...Array.from(cats).filter((c) => !order.includes(c)),
    ]
    return ordered
      .map((cat) => ({
        category: cat,
        tiles: cockpit.tiles.filter((t) => t.category === cat),
        links: cockpit.link_tiles.filter((t) => t.category === cat),
      }))
      .filter((g) => g.tiles.length > 0 || g.links.length > 0)
  }, [cockpit])

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {/* Header */}
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <Link
              href="/"
              className="mb-1 inline-flex items-center gap-1 text-xs text-[#6B7280] hover:text-[#1B3A5C]"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Home
            </Link>
            <h1 className="text-2xl font-bold text-[#1B3A5C]">CEO Cockpit</h1>
            <p className="mt-0.5 text-sm text-[#6B7280]">
              One headline KPI per report. Click any card to open the full report.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {cockpit && (
              <span className="text-xs text-[#9CA3AF]">
                Updated {fmtGeneratedAt(cockpit.generated_at)}
              </span>
            )}
            <button
              type="button"
              onClick={() => refetch()}
              disabled={isFetching}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-xs font-semibold text-[#1B3A5C] shadow-sm transition hover:bg-[#F9FAFB] disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Legend */}
        <div className="mb-5 flex flex-wrap items-center gap-3 text-[11px] text-[#6B7280]">
          {(["good", "warn", "bad", "neutral"] as TileStatus[]).map((st) => (
            <span key={st} className="inline-flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: STATUS_STYLES[st].dot }}
              />
              {STATUS_LABEL[st]}
            </span>
          ))}
        </div>

        {isError && (
          <div className="rounded-xl border border-[#FECACA] bg-[#FEF2F2] p-4 text-sm text-[#B91C1C]">
            Couldn&apos;t load the cockpit. The backend may be waking up — try Refresh in a
            few seconds.
          </div>
        )}

        {isLoading && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 12 }).map((_, i) => (
              <TileSkeleton key={i} />
            ))}
          </div>
        )}

        {cockpit &&
          grouped.map((group) => (
            <section key={group.category} className="mb-8">
              <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-[#94A3B8]">
                {group.category}
              </h2>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {group.tiles.map((t) => (
                  <KpiTile key={t.key} tile={t} />
                ))}
                {group.links.map((t) => (
                  <LinkTile key={t.key} tile={t} />
                ))}
              </div>
            </section>
          ))}
      </div>
    </div>
  )
}

export default function CeoCockpitPage() {
  return (
    <ReportGuard reportKey="ceo-cockpit">
      <CockpitContent />
    </ReportGuard>
  )
}
