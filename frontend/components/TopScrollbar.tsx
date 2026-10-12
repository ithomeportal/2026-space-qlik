"use client"

import { useEffect, useRef, useState } from "react"

/**
 * A horizontal scrollbar ABOVE a wide table (Bruno PDF 2026-10-12 R3), kept in
 * lock-step with the table box's own bottom scrollbar — which stays exactly as
 * it was. Scrolling either one moves the other.
 *
 * Usage: hold the scroll box in STATE via a callback ref (`ref={setEl}`), not
 * a `useRef`: the box mounts only after the data loads, and a ref object never
 * re-runs the effect that has to observe it.
 *
 * The strip's inner width tracks the box's `scrollWidth` through a
 * ResizeObserver on the box AND its table, so expanding a pivot row, a new
 * page or a window resize all re-measure. It renders nothing (zero height)
 * when the table fits, so it never shows a dead scrollbar.
 */
export function TopScrollbar({ target }: { target: HTMLElement | null }) {
  const barRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [overflows, setOverflows] = useState(false)
  // Which side is driving the current scroll, so the echo from the other side
  // setting scrollLeft is not fed back.
  const driver = useRef<"bar" | "target" | null>(null)

  useEffect(() => {
    if (!target) return
    const measure = () => {
      const bar = barRef.current
      // ⚠ Match the SCROLL RANGES, not the content widths: the box loses its
      // vertical scrollbar's width (~17px on Windows) from `clientWidth`, the
      // strip does not. Sized to `scrollWidth` alone, the strip's max
      // scrollLeft fell 17px short and every sync clamped the table back off
      // its right edge — the last column could never be fully revealed.
      const range = target.scrollWidth - target.clientWidth
      setWidth(range + (bar?.clientWidth ?? target.clientWidth))
      setOverflows(range > 1)
      if (bar) bar.scrollLeft = target.scrollLeft
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(target)
    if (barRef.current) ro.observe(barRef.current)
    for (const child of Array.from(target.children)) ro.observe(child)
    return () => ro.disconnect()
  }, [target])

  useEffect(() => {
    const bar = barRef.current
    if (!target || !bar) return
    const sync = (from: "bar" | "target") => () => {
      if (driver.current && driver.current !== from) return
      driver.current = from
      const src = from === "bar" ? bar : target
      const dst = from === "bar" ? target : bar
      // A tolerance, not `!==`: at 110%/125% zoom Chrome snaps scrollLeft to
      // device pixels differently per element, and an exact compare would
      // ping-pong the two boxes by a fraction of a pixel while dragging.
      if (Math.abs(dst.scrollLeft - src.scrollLeft) > 1) dst.scrollLeft = src.scrollLeft
      requestAnimationFrame(() => {
        driver.current = null
      })
    }
    const onBar = sync("bar")
    const onTarget = sync("target")
    bar.addEventListener("scroll", onBar, { passive: true })
    target.addEventListener("scroll", onTarget, { passive: true })
    return () => {
      bar.removeEventListener("scroll", onBar)
      target.removeEventListener("scroll", onTarget)
    }
  }, [target, overflows])

  return (
    <div
      ref={barRef}
      aria-hidden="true"
      data-testid="top-scrollbar"
      className={overflows ? "mb-1 overflow-x-auto overflow-y-hidden" : "h-0 overflow-hidden"}
      // A floor for OVERLAY scrollbars (macOS): they add no height, so the
      // 1px spacer alone would leave nothing to grab. Classic scrollbars
      // (Windows) already exceed it.
      style={overflows ? { minHeight: 12 } : undefined}
    >
      <div style={{ width, height: overflows ? 1 : 0 }} />
    </div>
  )
}
