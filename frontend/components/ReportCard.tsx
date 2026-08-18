"use client"

import { motion } from "framer-motion"
import Link from "next/link"
import { ExternalLink, Star } from "lucide-react"
import type { Report, AppItem } from "@/lib/api"
import { useToggleFavorite } from "@/lib/api"
import { getReportIcon } from "./ReportIcons"


interface ReportCardProps {
  report: Report
  view?: "tiles" | "list"
}

/**
 * Favourite toggle (Bruno PDF 2026-08-17 R1: "a star to click, shown over each
 * icon, visible").
 *
 * Two things this must get right:
 *  - The whole card is a <Link>, so the click has to be stopped dead
 *    (preventDefault + stopPropagation) or starring a report navigates to it.
 *  - It renders OUTSIDE the icon box, which is `overflow-hidden` — a star
 *    positioned on the box itself would be clipped at the corner.
 *
 * Shown at all times (outline when off) rather than on hover: hover-only
 * controls are invisible on touch, and the home grid is used on tablets.
 */
function FavoriteStar({ report, size }: { report: Report; size: "tile" | "list" }) {
  const toggle = useToggleFavorite()
  const on = !!report.is_favorited
  const box = size === "tile" ? "h-6 w-6 -right-1 -top-1" : "h-5 w-5"
  const icon = size === "tile" ? "h-3.5 w-3.5" : "h-3 w-3"

  return (
    <button
      type="button"
      aria-label={on ? `Remove ${report.title} from favorites` : `Add ${report.title} to favorites`}
      aria-pressed={on}
      title={on ? "Remove from favorites" : "Add to favorites"}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        toggle.mutate(report.id)
      }}
      className={`${box} ${
        size === "tile" ? "absolute z-10" : ""
      } flex shrink-0 items-center justify-center rounded-full border border-[#E5E7EB] bg-white shadow-sm transition-colors hover:border-[#F59E0B]`}
    >
      <Star
        className={`${icon} transition-colors ${
          on ? "fill-[#F59E0B] text-[#F59E0B]" : "text-[#9CA3AF]"
        }`}
      />
    </button>
  )
}

/** Tile view — square app-icon style with 3-band family gradient + sibling tag */
function TileView({ report }: ReportCardProps) {
  const { icon: Icon, gradient, tag, tagBg } = getReportIcon(report.title, report.category)

  return (
    <motion.div
      whileHover={{ y: -4, scale: 1.02 }}
      transition={{ duration: 0.15, ease: "easeOut" }}
    >
      <Link href={`/reports/${report.id}`} className="block">
        <div className="group flex cursor-pointer flex-col items-center text-center">
          {/* `relative` wrapper so the star can sit over the icon's corner
              without being clipped by its `overflow-hidden`. */}
          <div className="relative">
          <FavoriteStar report={report} size="tile" />
          <div
            className="relative flex h-20 w-20 items-center justify-center overflow-hidden rounded-[22px] shadow-md transition-shadow group-hover:shadow-xl"
            style={{ background: gradient }}
          >
            <Icon
              className="h-9 w-9 text-white"
              style={{ filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.4))" }}
            />
            {tag && (
              <span
                className="absolute bottom-1 right-1 rounded px-1 py-0.5 text-[9px] font-bold leading-none text-white shadow-sm"
                style={{ backgroundColor: tagBg }}
              >
                {tag}
              </span>
            )}
          </div>
          </div>
          <p className="mt-2 line-clamp-2 max-w-[100px] text-xs font-medium text-[#111827]">
            {report.title}
          </p>
        </div>
      </Link>
    </motion.div>
  )
}

/** List view — row with icon, title, and note */
function ListView({ report }: ReportCardProps) {
  const { icon: Icon, gradient, tag, tagBg } = getReportIcon(report.title, report.category)

  return (
    <Link href={`/reports/${report.id}`}>
      <div className="group flex cursor-pointer items-center gap-4 rounded-lg border border-transparent px-4 py-3 transition-colors hover:border-[#E5E7EB] hover:bg-[#F9FAFB]">
        <div
          className="relative flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl shadow-sm"
          style={{ background: gradient }}
        >
          <Icon
            className="h-5 w-5 text-white"
            style={{ filter: "drop-shadow(0 1px 1px rgba(0,0,0,0.4))" }}
          />
          {tag && (
            <span
              className="absolute -bottom-0.5 -right-0.5 rounded px-1 text-[8px] font-bold leading-tight text-white shadow-sm"
              style={{ backgroundColor: tagBg }}
            >
              {tag}
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-[#111827]">
            {report.title}
          </p>
          {report.description && (
            <p className="truncate text-xs text-[#6B7280]">
              {report.description}
            </p>
          )}
        </div>
        <div className="hidden min-w-0 flex-1 text-xs text-[#6B7280] sm:block">
          {report.note ?? ""}
        </div>
        <FavoriteStar report={report} size="list" />
      </div>
    </Link>
  )
}

export function ReportCard(props: ReportCardProps) {
  if (props.view === "list") return <ListView {...props} />
  return <TileView {...props} />
}

/** App card — external link tile with locally stored favicon */
interface AppCardProps {
  app: AppItem
  view?: "tiles" | "list"
}

function AppTileView({ app }: AppCardProps) {
  return (
    <motion.div
      whileHover={{ y: -4, scale: 1.02 }}
      transition={{ duration: 0.15, ease: "easeOut" }}
    >
      <a
        href={app.url}
        target="_blank"
        rel="noopener noreferrer"
        className="block"
      >
        <div className="group flex cursor-pointer flex-col items-center text-center">
          <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-md ring-1 ring-[#E5E7EB] transition-shadow group-hover:shadow-xl">
            {app.icon_data ? (
              <img
                src={app.icon_data}
                alt={app.title}
                className="h-7 w-7 rounded-md"
              />
            ) : (
              <ExternalLink className="h-6 w-6 text-[#2563EB]" />
            )}
            {/* External link badge */}
            <div className="absolute -bottom-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-[#2563EB] shadow-sm">
              <ExternalLink className="h-2 w-2 text-white" />
            </div>
          </div>
          <p className="mt-1.5 line-clamp-2 max-w-[80px] text-[11px] font-medium text-[#111827]">
            {app.title}
          </p>
        </div>
      </a>
    </motion.div>
  )
}

function AppListView({ app }: AppCardProps) {
  return (
    <a href={app.url} target="_blank" rel="noopener noreferrer">
      <div className="group flex cursor-pointer items-center gap-4 rounded-lg border border-transparent px-4 py-3 transition-colors hover:border-[#E5E7EB] hover:bg-[#F9FAFB]">
        <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white shadow-sm ring-1 ring-[#E5E7EB]">
          {app.icon_data ? (
            <img
              src={app.icon_data}
              alt={app.title}
              className="h-6 w-6 rounded"
            />
          ) : (
            <ExternalLink className="h-5 w-5 text-[#2563EB]" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-[#111827]">
            {app.title}
          </p>
          {app.description && (
            <p className="truncate text-xs text-[#6B7280]">
              {app.description}
            </p>
          )}
        </div>
        <div className="shrink-0">
          <span className="rounded-full bg-[#EFF6FF] px-2.5 py-1 text-xs font-medium text-[#2563EB]">
            App
          </span>
        </div>
      </div>
    </a>
  )
}

export function AppCard(props: AppCardProps) {
  if (props.view === "list") return <AppListView {...props} />
  return <AppTileView {...props} />
}
