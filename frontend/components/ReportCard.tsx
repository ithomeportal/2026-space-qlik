"use client"

import { motion } from "framer-motion"
import Link from "next/link"
import { ExternalLink } from "lucide-react"
import type { Report, AppItem } from "@/lib/api"
import { getReportIcon } from "./ReportIcons"


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

/** List view — row with icon, title, and note */
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
        <div className="hidden min-w-0 flex-1 text-xs text-[#6B7280] sm:block">
          {report.note ?? ""}
        </div>
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
          <div className="relative flex h-20 w-20 items-center justify-center rounded-[22px] bg-white shadow-md ring-1 ring-[#E5E7EB] transition-shadow group-hover:shadow-xl">
            {app.icon_data ? (
              <img
                src={app.icon_data}
                alt={app.title}
                className="h-10 w-10 rounded-md"
              />
            ) : (
              <ExternalLink className="h-9 w-9 text-[#2563EB]" />
            )}
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
