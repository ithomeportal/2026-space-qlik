"use client"

import { motion } from "framer-motion"
import Link from "next/link"
import { Star } from "lucide-react"
import type { Report } from "@/lib/api"
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
  isFavorited?: boolean
  onToggleFavorite?: (id: string) => void
  view?: "tiles" | "list"
}

function FavoriteButton({
  reportId,
  isFavorited,
  onToggleFavorite,
}: {
  reportId: string
  isFavorited?: boolean
  onToggleFavorite?: (id: string) => void
}) {
  if (!onToggleFavorite) return null
  return (
    <button
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        onToggleFavorite(reportId)
      }}
      className="p-1 transition-colors hover:text-[#2563EB]"
    >
      <Star
        className={`h-4 w-4 ${
          isFavorited ? "fill-[#2563EB] text-[#2563EB]" : "text-[#9CA3AF]"
        }`}
      />
    </button>
  )
}

/** Tile view — square app-icon style */
function TileView({ report, isFavorited, onToggleFavorite }: ReportCardProps) {
  const { icon: Icon, bg } = getReportIcon(report.title, report.category)

  return (
    <motion.div
      whileHover={{ y: -4, scale: 1.02 }}
      transition={{ duration: 0.15, ease: "easeOut" }}
    >
      <Link href={`/reports/${report.id}`} className="block">
        <div className="group flex cursor-pointer flex-col items-center text-center">
          {/* App icon */}
          <div
            className={`relative flex h-20 w-20 items-center justify-center rounded-[22px] bg-gradient-to-br ${bg} shadow-md transition-shadow group-hover:shadow-xl`}
          >
            <Icon className="h-9 w-9 text-white" />
            {/* Favorite star overlay */}
            <div className="absolute -right-1 -top-1">
              <FavoriteButton
                reportId={report.id}
                isFavorited={isFavorited}
                onToggleFavorite={onToggleFavorite}
              />
            </div>
          </div>
          {/* Label */}
          <p className="mt-2 line-clamp-2 max-w-[100px] text-xs font-medium text-[#111827]">
            {report.title}
          </p>
        </div>
      </Link>
    </motion.div>
  )
}

/** List view — row with icon, title, category, owner, date */
function ListView({ report, isFavorited, onToggleFavorite }: ReportCardProps) {
  const { icon: Icon, bg } = getReportIcon(report.title, report.category)

  return (
    <Link href={`/reports/${report.id}`}>
      <div className="group flex cursor-pointer items-center gap-4 rounded-lg border border-transparent px-4 py-3 transition-colors hover:border-[#E5E7EB] hover:bg-[#F9FAFB]">
        {/* Icon */}
        <div
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${bg} shadow-sm`}
        >
          <Icon className="h-5 w-5 text-white" />
        </div>

        {/* Title + description */}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-[#111827]">
            {report.title}
          </p>
          {report.description && (
            <p className="truncate text-xs text-[#6B7280]">{report.description}</p>
          )}
        </div>

        {/* Category */}
        <div className="hidden w-28 shrink-0 sm:block">
          {report.category && (
            <span className="rounded-full bg-[#F3F4F6] px-2.5 py-1 text-xs font-medium text-[#374151]">
              {report.category}
            </span>
          )}
        </div>

        {/* Owner */}
        <div className="hidden w-24 shrink-0 text-xs text-[#6B7280] md:block">
          {report.owner_name ?? "—"}
        </div>

        {/* Updated */}
        <div className="hidden w-24 shrink-0 text-right text-xs text-[#6B7280] lg:block">
          {formatTimeAgo(report.last_reload)}
        </div>

        {/* Favorite */}
        <div className="shrink-0">
          <FavoriteButton
            reportId={report.id}
            isFavorited={isFavorited}
            onToggleFavorite={onToggleFavorite}
          />
        </div>
      </div>
    </Link>
  )
}

export function ReportCard(props: ReportCardProps) {
  if (props.view === "list") return <ListView {...props} />
  return <TileView {...props} />
}
