import type { ReactNode } from "react"
import { FavoritesSidebar } from "@/components/FavoritesSidebar"

/**
 * Shared chrome for every report route: the Favorites rail, plus a continuous
 * page backdrop.
 *
 * ── The backdrop (2026-08-17) ───────────────────────────────────────────────
 * `app/layout.tsx` paints `<body>` white, while each report's own root paints
 * `#F9FAFB`. Any document height beyond that root therefore renders as a band of
 * pure WHITE below the last card — which is exactly what was reported against
 * the Ops Portal "By Order" table on 2026-08-17 (screenshot: the page background
 * stops dead at the card and everything below it is #FFFFFF, not #F9FAFB).
 *
 * The dead space itself could not be reproduced: a harness serving the real page
 * with real row counts (807 orders / 50 per page / 82 covered loads) measured a
 * 16px gap — the body's own `py-4` — in all three view modes at 1280x720,
 * 1600x900, 1920x1080 and 2560x1300, and scrollY clamped correctly when
 * switching modes while scrolled to the bottom. So rather than guess at a CSS
 * culprit in a component five reports share, this makes the page background
 * continuous: whatever the height turns out to be, it can never paint white.
 *
 * ── The rail (2026-09-09) ───────────────────────────────────────────────────
 * The wrapper became a flex ROW to seat `<FavoritesSidebar/>` beside the report.
 * Three constraints survive from the note above, and breaking any of them
 * regresses something that took a harness to find:
 *
 *   - Still no `overflow` here. The moment this element scrolls, it becomes the
 *     scroll container for everything inside it and the `sticky top-0` toolbars
 *     ~20 reports use stop resolving against the viewport. The rail owns its own
 *     `overflow-y-auto`, and nothing else in this subtree has one.
 *   - Still no padding. Report roots carry their own, and they are full-bleed
 *     columns (`flex min-h-[calc(100vh-64px)] flex-col`).
 *   - `min-w-0` on the content column is load-bearing. A flex item defaults to
 *     `min-width: auto`, so a report with a wide table (`min-w-[1100px]` inside
 *     an `overflow-x-auto` wrapper) would push the track wider than the viewport
 *     and give the whole page a horizontal scrollbar instead of scrolling the
 *     table.
 *
 * `/` does not pass through this layout, so the Home dashboard is untouched —
 * which is what the request asked for.
 */
export default function ReportsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-[calc(100vh-64px)] bg-[#F9FAFB]">
      <FavoritesSidebar />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}
