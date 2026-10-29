"use client"

import { usePathname } from "next/navigation"
import { Star } from "lucide-react"
import { usePreferences, useReports, useToggleFavorite, type Report } from "@/lib/api"

/**
 * ★ at the end of a report's title — mark / unmark the OPEN report as a favourite
 * (request 2026-10-29: "set & mark/unmark a report as Favorites when I open it").
 *
 * Same write as the Home grid star (`useToggleFavorite` → `pinned_reports`), and
 * its `onSettled` refreshes the in-report Favorites rail too. The report is found
 * by the URL: the LONGEST `custom_path` the pathname sits under, so a sub-page
 * (`/reports/dfw-losses/orders`) stars its parent and the 7 shared report bodies
 * (Ops Portal, XRay, Direct Compare…) star whichever copy is open.
 *
 * Disabled until preferences have loaded: the toggle rebuilds the WHOLE list from
 * them, so a click against an empty cache would drop every other favourite.
 */
export function findOpenReport(reports: Report[], pathname: string): Report | null {
  let best: Report | null = null
  for (const r of reports) {
    const p = r.custom_path
    if (!p || !(pathname === p || pathname.startsWith(`${p}/`))) continue
    if (!best || p.length > (best.custom_path ?? "").length) best = r
  }
  return best
}

export function FavoriteToggle() {
  const pathname = usePathname()
  const { data: reports } = useReports()
  const { data: prefs } = usePreferences()
  const toggle = useToggleFavorite()
  const report = findOpenReport(reports?.data ?? [], pathname)
  if (!report) return null
  const on = !!report.is_favorited
  const ready = !!prefs?.data && !toggle.isPending

  return (
    <button
      type="button"
      disabled={!ready}
      aria-label={on ? `Remove ${report.title} from favorites` : `Add ${report.title} to favorites`}
      aria-pressed={on}
      title={on ? "Remove from favorites" : "Add to favorites"}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        toggle.mutate(report.id)
      }}
      className="ml-1.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full align-middle transition-colors hover:bg-[#FEF3C7] disabled:opacity-50"
    >
      <Star className={`h-3.5 w-3.5 ${on ? "fill-[#F59E0B] text-[#F59E0B]" : "text-[#9CA3AF]"}`} />
    </button>
  )
}
