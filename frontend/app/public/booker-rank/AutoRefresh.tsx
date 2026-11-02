"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

/** Re-renders the server page on an interval — a TV has nobody to press F5.
 *
 * `router.refresh()` re-runs the server component with the same URL (and so the
 * same `?key=`), keeping client state and never flashing a blank screen. Every
 * `HARD_RELOAD_EVERY` refreshes the page reloads fully, so a TV that runs for
 * weeks picks up a new deploy and never accumulates browser state.
 */
const HARD_RELOAD_EVERY = 36

export function AutoRefresh({ intervalMs }: { intervalMs: number }) {
  const router = useRouter()

  useEffect(() => {
    let ticks = 0
    const id = window.setInterval(() => {
      ticks += 1
      if (ticks >= HARD_RELOAD_EVERY) {
        window.location.reload()
        return
      }
      router.refresh()
    }, intervalMs)
    return () => window.clearInterval(id)
  }, [router, intervalMs])

  return null
}
