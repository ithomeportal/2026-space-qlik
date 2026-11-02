/**
 * /public/booker-rank — the Booker Performance Scorecard "Rank" tab for the
 * floor TVs (request "space -- Public URL", 2026-11-02).
 *
 * NO LOGIN. Gated by `?key=` against `PUBLIC_DISPLAY_KEYS` (see
 * `lib/public-display.ts`); a missing/wrong key is a plain 404. Lives outside
 * `app/reports/`, so it has no ReportGuard, no favorites rail and no session.
 * The root Header hides itself on `/public/*`.
 */
import type { Metadata } from "next"
import { notFound } from "next/navigation"
import {
  PUBLIC_DISPLAY_REFRESH_MS,
  fetchPublicDisplay,
  isValidDisplayKey,
} from "@/lib/public-display"
import { fmtUpdatedAt, type PublicBookerRank } from "@/lib/public-display-format"
import { AutoRefresh } from "./AutoRefresh"
import { RankBoard } from "./RankBoard"

export const dynamic = "force-dynamic"
export const maxDuration = 60

export const metadata: Metadata = {
  title: "Booker Rank — UNILINK",
  robots: { index: false, follow: false },
}

interface PageProps {
  searchParams: { [key: string]: string | string[] | undefined }
}

export default async function PublicBookerRankPage({ searchParams }: PageProps) {
  if (!isValidDisplayKey(searchParams.key)) notFound()

  const result = await fetchPublicDisplay<PublicBookerRank>("booker-rank")

  return (
    <div className="min-h-screen bg-[#F3F4F6] p-6">
      <AutoRefresh intervalMs={PUBLIC_DISPLAY_REFRESH_MS} />
      <div className="mb-5 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-[#1B3A5C]">
            <span className="text-lg font-bold text-[#D02228]">US</span>
          </div>
          <h1 className="text-4xl font-bold text-[#1B3A5C]">Booker Performance — Rank</h1>
        </div>
        <p className="text-lg text-[#4B5563]">
          {result.ok ? `Updated ${fmtUpdatedAt(result.fetchedAt)} CT` : "Reconnecting…"}
        </p>
      </div>

      {result.ok ? (
        <div className="grid gap-6">
          <RankBoard
            title="Rank — This Week"
            caption={`${result.data.current.week.label}${
              result.data.current.like_for_like ? " · vs same point last week" : ""
            }`}
            table={result.data.current}
            emptyText="No bookings yet this week."
          />
          <RankBoard
            title="Rank Last Week"
            caption={`${result.data.last_week.week.label} · ≥ ${result.data.last_week.min_bookings} bookings · by Cost Saving`}
            table={result.data.last_week}
            emptyText="No booker reached the minimum last week."
          />
        </div>
      ) : (
        <div className="rounded-xl border border-[#E5E7EB] bg-white p-16 text-center text-2xl text-[#6B7280]">
          Data temporarily unavailable — retrying automatically.
        </div>
      )}
    </div>
  )
}
