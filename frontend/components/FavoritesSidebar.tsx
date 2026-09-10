"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { ArrowDownAZ, ArrowUpAZ, ChevronLeft, ChevronRight, Flame, Star } from "lucide-react"
import { useFavoriteReports, logReportAccess, type FavoriteReport } from "@/lib/api"
import { useIsMobile } from "@/lib/use-is-mobile"
import { getReportIcon } from "./ReportIcons"

/**
 * The Favorites rail — a collapsible left column on every `/reports/*` route
 * (request 2026-09-09: "one click from any report to go directly to any of
 * them", so nobody has to go Home and back to switch).
 *
 * Home is deliberately untouched: this renders from `app/reports/layout.tsx`,
 * which `/` never passes through.
 *
 * Layout contract — the wrapper it lives in is a flex row, and this aside is
 * `self-start` + `sticky`. Both matter:
 *   - a stretched flex item has no room to move, so `sticky` would be inert;
 *   - `overflow-y-auto` is on THIS element only. Put it on an ancestor and it
 *     becomes the scroll container for the report beside it, which would break
 *     the `sticky top-0` toolbars ~20 reports rely on.
 */

const STORAGE_COLLAPSED = "space:favorites-rail:collapsed"
const STORAGE_SORT = "space:favorites-rail:sort"

/** Below this width the rail starts collapsed — a first-visit default only, an
 *  explicit choice always wins. Not `useIsMobile()`: that calls anything under
 *  1920px mobile, which would collapse the rail on ordinary laptops. */
const AUTO_COLLAPSE_BELOW_PX = 1280

type SortMode = "usage" | "az" | "za"

/** Most used → A→Z → Z→A → most used. The request asks for a usage default and
 *  a clickable header toggling alphabetical asc/desc; cycling through three
 *  keeps one control and never strands the user away from the default. */
const SORT_ORDER: readonly SortMode[] = ["usage", "az", "za"] as const

const SORT_LABEL: Record<SortMode, string> = {
  usage: "Most used",
  az: "A → Z",
  za: "Z → A",
}

function isSortMode(value: string | null): value is SortMode {
  return value === "usage" || value === "az" || value === "za"
}

/** localStorage is unavailable in private modes and throws rather than
 *  returning null, so every access is guarded. */
function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStored(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // A rail that forgets its width is fine; one that crashes the report is not.
  }
}

/**
 * Sorting is client-side on purpose: the server already returns usage order, and
 * re-fetching to re-alphabetise a list of five rows would put a Render cold
 * start between the click and the answer.
 *
 * ⚠ `use_count` is a plain number COALESCEd to 0 server-side — there is no null
 * sentinel here, so flipping the comparator cannot silently promote "unknown"
 * to the top the way a nullable measure would.
 */
function sortFavorites(rows: readonly FavoriteReport[], mode: SortMode): FavoriteReport[] {
  const byTitle = (a: FavoriteReport, b: FavoriteReport) => a.title.localeCompare(b.title)
  const copy = [...rows]
  if (mode === "az") return copy.sort(byTitle)
  if (mode === "za") return copy.sort((a, b) => byTitle(b, a))
  return copy.sort((a, b) => b.use_count - a.use_count || byTitle(a, b))
}

/**
 * True when `pathname` is this report, including deeper segments — the CEO
 * Executive Portal takes a REQUIRED `/{division}/…` path segment, so an
 * equality check would leave it unhighlighted on every page the user can
 * actually reach.
 */
function isActivePath(pathname: string, customPath: string | null): boolean {
  if (!customPath) return false
  return pathname === customPath || pathname.startsWith(`${customPath}/`)
}

function FavoriteRow({
  report,
  active,
  collapsed,
}: {
  report: FavoriteReport
  active: boolean
  collapsed: boolean
}) {
  const { icon: Icon, gradient } = getReportIcon(report.title, report.category)
  // A pinned report always has a `custom_path` (every report is code-made), but
  // a legacy row without one would render a dead link — send it through the
  // resolver instead of nowhere.
  const href = report.custom_path ?? `/reports/${report.id}`

  return (
    <Link
      href={href}
      title={report.title}
      aria-current={active ? "page" : undefined}
      onClick={() => logReportAccess(report.id)}
      className={`flex items-center gap-2 rounded-lg transition-colors ${
        collapsed ? "justify-center p-1.5" : "px-2 py-1.5"
      } ${active ? "bg-[#1B3A5C] text-white" : "text-[#374151] hover:bg-[#E5E7EB]"}`}
    >
      <span
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg shadow-sm"
        style={{ background: gradient }}
      >
        <Icon
          className="h-4 w-4 text-white"
          style={{ filter: "drop-shadow(0 1px 1px rgba(0,0,0,0.4))" }}
        />
      </span>
      {!collapsed && (
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium leading-tight">
          {report.title}
        </span>
      )}
    </Link>
  )
}

export function FavoritesSidebar() {
  const pathname = usePathname()
  const isMobile = useIsMobile()
  const { data, isLoading } = useFavoriteReports(isMobile)

  const [collapsed, setCollapsed] = useState(false)
  const [sort, setSort] = useState<SortMode>("usage")

  // Read persisted state after mount — reading it during render would make the
  // server HTML and the first client render disagree.
  useEffect(() => {
    const storedCollapsed = readStored(STORAGE_COLLAPSED)
    if (storedCollapsed === "1" || storedCollapsed === "0") {
      setCollapsed(storedCollapsed === "1")
    } else if (window.innerWidth < AUTO_COLLAPSE_BELOW_PX) {
      setCollapsed(true)
    }
    const storedSort = readStored(STORAGE_SORT)
    if (isSortMode(storedSort)) setSort(storedSort)
  }, [])

  const favorites = useMemo(() => sortFavorites(data?.data ?? [], sort), [data, sort])

  function toggleCollapsed() {
    setCollapsed((prev) => {
      writeStored(STORAGE_COLLAPSED, prev ? "0" : "1")
      return !prev
    })
  }

  function cycleSort() {
    setSort((prev) => {
      const next = SORT_ORDER[(SORT_ORDER.indexOf(prev) + 1) % SORT_ORDER.length]
      writeStored(STORAGE_SORT, next)
      return next
    })
  }

  const SortIcon = sort === "az" ? ArrowDownAZ : sort === "za" ? ArrowUpAZ : Flame

  return (
    <aside
      aria-label="Favorite reports"
      className={`sticky top-16 z-30 flex h-[calc(100vh-64px)] shrink-0 flex-col self-start border-r border-[#E5E7EB] bg-[#F9FAFB] ${
        collapsed ? "w-14" : "w-56"
      }`}
    >
      {/* Header — the label cycles the order, the chevron collapses. Two
          separate controls: one button doing both would make every attempt to
          re-sort also fold the rail away. */}
      <div
        className={`flex shrink-0 items-center gap-1 border-b border-[#E5E7EB] px-2 py-2 ${
          collapsed ? "justify-center" : ""
        }`}
      >
        {!collapsed && (
          <button
            type="button"
            onClick={cycleSort}
            title={`Sorted by ${SORT_LABEL[sort]} — click to change`}
            aria-label={`Sorted by ${SORT_LABEL[sort]}. Click to change the order.`}
            className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-[#E5E7EB]"
          >
            <Star className="h-3.5 w-3.5 shrink-0 fill-[#F59E0B] text-[#F59E0B]" />
            <span className="truncate text-[11px] font-semibold uppercase tracking-wider text-[#6B7280]">
              Favorites
            </span>
            <span className="text-[11px] text-[#9CA3AF]">({favorites.length})</span>
            <SortIcon className="ml-auto h-3.5 w-3.5 shrink-0 text-[#9CA3AF]" />
          </button>
        )}
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Expand favorites" : "Collapse favorites"}
          title={collapsed ? "Expand favorites" : "Collapse favorites"}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[#6B7280] transition-colors hover:bg-[#E5E7EB]"
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </button>
      </div>

      {/* The ONLY scroll container in this subtree — an arbitrarily long
          favourites list scrolls here rather than stretching the page. */}
      <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto p-2">
        {isLoading ? (
          <div className="space-y-1.5 p-1">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-7 animate-pulse rounded-lg bg-[#E5E7EB]" />
            ))}
          </div>
        ) : favorites.length > 0 ? (
          favorites.map((report) => (
            <FavoriteRow
              key={report.id}
              report={report}
              active={isActivePath(pathname, report.custom_path)}
              collapsed={collapsed}
            />
          ))
        ) : collapsed ? (
          <div className="flex justify-center pt-2" title="No favorites yet">
            <Star className="h-4 w-4 text-[#D1D5DB]" />
          </div>
        ) : (
          <p className="px-2 py-3 text-[11px] leading-relaxed text-[#9CA3AF]">
            No favorites yet — click the star on any report from{" "}
            <Link href="/" className="text-[#2563EB] hover:underline">
              Home
            </Link>
            .
          </p>
        )}
      </nav>
    </aside>
  )
}
