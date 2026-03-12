"use client"

import { motion } from "framer-motion"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Star } from "lucide-react"
import type { Report } from "@/lib/api"

const CATEGORY_COLORS: Record<string, string> = {
  Executive: "bg-[#1B3A5C] text-white",
  Finance: "bg-[#1D4ED8] text-white",
  Operations: "bg-[#D97706] text-white",
  Sales: "bg-[#7C3AED] text-white",
  HR: "bg-[#0D9488] text-white",
  IT: "bg-[#6366F1] text-white",
}

function getInitials(title: string): string {
  return title
    .split(/[\s-]+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()
}

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
}

export function ReportCard({ report, isFavorited, onToggleFavorite }: ReportCardProps) {
  const categoryColor = CATEGORY_COLORS[report.category ?? ""] ?? "bg-gray-500 text-white"

  return (
    <motion.div
      whileHover={{ y: -4 }}
      transition={{ duration: 0.15, ease: "easeOut" }}
    >
      <Link href={`/reports/${report.id}`}>
        <Card className="group h-full cursor-pointer border-[#E5E7EB] transition-shadow duration-150 hover:shadow-lg">
          <CardContent className="flex h-full flex-col gap-3 p-5">
            {/* Top row: icon + category + favorite */}
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-xs font-bold ${categoryColor}`}
                >
                  {getInitials(report.title)}
                </div>
                {report.category && (
                  <Badge className={`text-[11px] uppercase ${categoryColor}`}>
                    {report.category}
                  </Badge>
                )}
              </div>
              {onToggleFavorite && (
                <button
                  onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    onToggleFavorite(report.id)
                  }}
                  className="p-1 transition-colors hover:text-[#2563EB]"
                >
                  <Star
                    className={`h-4 w-4 ${
                      isFavorited
                        ? "fill-[#2563EB] text-[#2563EB]"
                        : "text-[#6B7280]"
                    }`}
                  />
                </button>
              )}
            </div>

            {/* Title */}
            <h3 className="line-clamp-2 text-[15px] font-semibold text-[#111827]">
              {report.title}
            </h3>

            {/* Description */}
            {report.description && (
              <p className="line-clamp-2 text-sm text-[#6B7280]">
                {report.description}
              </p>
            )}

            {/* Footer */}
            <div className="mt-auto flex items-center justify-between pt-2 text-xs text-[#6B7280]">
              {report.owner_name && <span>{report.owner_name}</span>}
              <span>Updated {formatTimeAgo(report.last_reload)}</span>
            </div>
          </CardContent>
        </Card>
      </Link>
    </motion.div>
  )
}
