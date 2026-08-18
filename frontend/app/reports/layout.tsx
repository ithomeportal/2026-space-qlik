import type { ReactNode } from "react"

/**
 * Shared backdrop for every report route.
 *
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
 * Deliberately background + min-height only — no padding, no flex, no overflow.
 * Report roots keep their own layout, and `position: sticky` still resolves
 * against the viewport because this wrapper never becomes a scroll container.
 */
export default function ReportsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-[calc(100vh-64px)] bg-[#F9FAFB]">{children}</div>
  )
}
