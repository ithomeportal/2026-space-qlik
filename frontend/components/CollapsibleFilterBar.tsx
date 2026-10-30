"use client"

import { useEffect, useId, useState, type ReactNode } from "react"
import { ChevronDown, ChevronUp, SlidersHorizontal } from "lucide-react"

/**
 * The sticky filter header every report shares (request 2026-10-30, mobile
 * screenshots from the Samsung Z Fold and the iPhone Fold).
 *
 * ── Why it is collapsible ───────────────────────────────────────────────────
 * On a phone a report's filters wrap into 4-6 rows, and because the bar is
 * sticky it kept ~45% (Fold) to ~70% (iPhone) of the screen while scrolling,
 * leaving a strip for the report itself. "Hide filters" folds it to a slim
 * strip; the choice is remembered per DEVICE (not per report), so a director
 * who folds it once on the phone never sees the tall bar again there, while
 * the same person's desktop keeps its own setting.
 *
 * ── Why `top-16` and not `top-0` ────────────────────────────────────────────
 * `<Header/>` is `sticky top-0 z-50 h-16`. The 24 hand-written bars this
 * replaces were ALSO `sticky top-0`, so once scrolled their first 64px sat
 * BEHIND the header: the Ops Portal's Range row and the Executive portal's
 * Division row were invisible on mobile, and a one-row desktop bar vanished
 * entirely. Sticking at the header's height is the fix. Keep the two in step
 * if the header height ever changes (the Favorites rail uses `top-16` too).
 *
 * ── Why the children stay MOUNTED when collapsed ────────────────────────────
 * The bar is hidden with the `hidden` attribute, never unmounted: filter
 * widgets such as MultiSelectChips keep local state (search text, open
 * popovers) that a remount would silently reset.
 *
 * `z-10` is deliberate — the bars were `z-10` before, and the pickers that drop
 * out of them must keep painting over the report below.
 */

const STORAGE_COLLAPSED = "space:filter-bar:collapsed"

const DEFAULT_CLASS = "border-b border-[#E5E7EB] bg-white shadow-sm"

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
    // A bar that forgets it was folded is fine; one that crashes the report is not.
  }
}

export function CollapsibleFilterBar({
  children,
  className = DEFAULT_CLASS,
}: {
  children: ReactNode
  /** Visual shell (border, background, radius, margin). Sticky positioning
   *  is owned here and must not be passed in. */
  className?: string
}) {
  const contentId = useId()
  const [collapsed, setCollapsed] = useState(false)

  // Read persisted state after mount — reading it during render would make the
  // server HTML and the first client render disagree.
  useEffect(() => {
    if (readStored(STORAGE_COLLAPSED) === "1") setCollapsed(true)
  }, [])

  function toggle() {
    setCollapsed((prev) => {
      writeStored(STORAGE_COLLAPSED, prev ? "0" : "1")
      return !prev
    })
  }

  return (
    <div className={`sticky top-16 z-10 ${className}`}>
      <div id={contentId} hidden={collapsed}>
        {children}
      </div>

      {collapsed ? (
        <button
          type="button"
          onClick={toggle}
          aria-expanded={false}
          aria-controls={contentId}
          className="flex w-full items-center gap-2 px-4 py-1.5 text-left text-xs text-[#374151] hover:bg-[#F9FAFB]"
        >
          <SlidersHorizontal className="h-3.5 w-3.5 text-[#1B3A5C]" />
          <span className="font-semibold text-[#1B3A5C]">Filters</span>
          <span className="text-[#9CA3AF]">hidden — tap to show</span>
          <ChevronDown className="ml-auto h-4 w-4 text-[#6B7280]" />
        </button>
      ) : (
        // Hangs BELOW the bar's edge so it adds no height to the bar itself.
        <button
          type="button"
          onClick={toggle}
          aria-expanded={true}
          aria-controls={contentId}
          className="absolute right-4 top-full flex items-center gap-1 rounded-b-md border border-t-0 border-[#E5E7EB] bg-white px-2 py-0.5 text-[11px] text-[#6B7280] shadow-sm hover:text-[#111827]"
        >
          <ChevronUp className="h-3.5 w-3.5" />
          Hide filters
        </button>
      )}
    </div>
  )
}
