"use client"

import { motion } from "framer-motion"
import Link from "next/link"
import { ExternalLink } from "lucide-react"
import type { Report, AppItem } from "@/lib/api"
import { getReportIcon } from "./ReportIcons"

function formatTimeAgo(date: string | null): string {
  if (!date) return "Unknown"
  const diff = Date.now() - new Date(date).getTime()
  const hours = Math.floor(diff / (1000 * 60 * 60))
  if (hours < 1) return "Just now"
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

interface ReportCardProps {
  report: Report
  view?: "tiles" | "list"
}

/** Tile view — square app-icon style */
function TileView({ report }: ReportCardProps) {
  const { icon: Icon, bg } = getReportIcon(report.title, report.category)

  return (
    <motion.div
      whileHover={{ y: -4, scale: 1.02 }}
      transition={{ duration: 0.15, ease: "easeOut" }}
    >
      <Link href={`/reports/${report.id}`} className="block">
        <div className="group flex cursor-pointer flex-col items-center text-center">
          <div
            className={`flex h-20 w-20 items-center justify-center rounded-[22px] bg-gradient-to-br ${bg} shadow-md transition-shadow group-hover:shadow-xl`}
          >
            <Icon className="h-9 w-9 text-white" />
          </div>
          <p className="mt-2 line-clamp-2 max-w-[100px] text-xs font-medium text-[#111827]">
            {report.title}
          </p>
        </div>
      </Link>
    </motion.div>
  )
}

/** List view — row with icon, title, category, owner, date */
function ListView({ report }: ReportCardProps) {
  const { icon: Icon, bg } = getReportIcon(report.title, report.category)

  return (
    <Link href={`/reports/${report.id}`}>
      <div className="group flex cursor-pointer items-center gap-4 rounded-lg border border-transparent px-4 py-3 transition-colors hover:border-[#E5E7EB] hover:bg-[#F9FAFB]">
        <div
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${bg} shadow-sm`}
        >
          <Icon className="h-5 w-5 text-white" />
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
        <div className="hidden w-28 shrink-0 sm:block">
          {report.category && (
            <span className="rounded-full bg-[#F3F4F6] px-2.5 py-1 text-xs font-medium text-[#374151]">
              {report.category}
            </span>
          )}
        </div>
        <div className="hidden w-24 shrink-0 text-xs text-[#6B7280] md:block">
          {report.owner_name ?? "—"}
        </div>
        <div className="hidden w-24 shrink-0 text-right text-xs text-[#6B7280] lg:block">
          {formatTimeAgo(report.last_reload)}
        </div>
      </div>
    </Link>
  )
}

export function ReportCard(props: ReportCardProps) {
  if (props.view === "list") return <ListView {...props} />
  return <TileView {...props} />
}

/** Get favicon URL from an app URL using Google's favicon service */
function getFaviconUrl(url: string, size: number = 64): string {
  try {
    const domain = new URL(url).hostname
    return `https://www.google.com/s2/favicons?domain=${domain}&sz=${size}`
  } catch {
    return ""
  }
}

/** App card — external link tile with favicon from the app's URL */
interface AppCardProps {
  app: AppItem
  view?: "tiles" | "list"
}

function AppTileView({ app }: AppCardProps) {
  const faviconUrl = getFaviconUrl(app.url, 64)

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
          <div className="relative flex h-20 w-20 items-center justify-center rounded-[22px] bg-white shadow-md ring-1 ring-[#E5E7EB] transition-shadow group-hover:shadow-xl">
            {faviconUrl ? (
              <img
                src={faviconUrl}
                alt={app.title}
                className="h-10 w-10 rounded-md"
                onError={(e) => {
                  e.currentTarget.style.display = "none"
                  e.currentTarget.nextElementSibling?.classList.remove("hidden")
                }}
              />
            ) : null}
            <ExternalLink
              className={`h-9 w-9 text-[#2563EB] ${faviconUrl ? "hidden" : ""}`}
            />
            {/* External link badge */}
            <div className="absolute -bottom-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-[#2563EB] shadow-sm">
              <ExternalLink className="h-2.5 w-2.5 text-white" />
            </div>
          </div>
          <p className="mt-2 line-clamp-2 max-w-[100px] text-xs font-medium text-[#111827]">
            {app.title}
          </p>
        </div>
      </a>
    </motion.div>
  )
}

function AppListView({ app }: AppCardProps) {
  const faviconUrl = getFaviconUrl(app.url, 32)

  return (
    <a href={app.url} target="_blank" rel="noopener noreferrer">
      <div className="group flex cursor-pointer items-center gap-4 rounded-lg border border-transparent px-4 py-3 transition-colors hover:border-[#E5E7EB] hover:bg-[#F9FAFB]">
        <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white shadow-sm ring-1 ring-[#E5E7EB]">
          {faviconUrl ? (
            <img
              src={faviconUrl}
              alt={app.title}
              className="h-6 w-6 rounded"
              onError={(e) => {
                e.currentTarget.style.display = "none"
                e.currentTarget.nextElementSibling?.classList.remove("hidden")
              }}
            />
          ) : null}
          <ExternalLink
            className={`h-5 w-5 text-[#2563EB] ${faviconUrl ? "hidden" : ""}`}
          />
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
