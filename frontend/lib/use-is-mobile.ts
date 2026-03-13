"use client"

import { useState, useEffect } from "react"

const DESKTOP_MIN_WIDTH = 1920

/**
 * Returns true when viewport width is below 1920px (mobile/tablet).
 * Desktop minimum resolution is 1920x1080 — anything below is treated
 * as a responsive mobile device that should see (Mob) reports.
 */
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    function check() {
      setIsMobile(window.innerWidth < DESKTOP_MIN_WIDTH)
    }
    check()
    window.addEventListener("resize", check)
    return () => window.removeEventListener("resize", check)
  }, [])

  return isMobile
}
