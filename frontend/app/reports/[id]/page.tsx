"use client"

import { useParams } from "next/navigation"
import { useReport } from "@/lib/api"
import { QlikEmbed } from "@/components/QlikEmbed"
import { Skeleton } from "@/components/ui/skeleton"
import { ArrowLeft } from "lucide-react"
import Link from "next/link"

export default function ReportViewerPage() {
  const { id } = useParams<{ id: string }>()
  const { data: reportRes, isLoading } = useReport(id)

  if (isLoading) {
    return (
      <div className="flex h-[calc(100vh-64px)] items-center justify-center">
        <div className="space-y-4 text-center">
          <Skeleton className="mx-auto h-8 w-64" />
          <Skeleton className="mx-auto h-4 w-40" />
        </div>
      </div>
    )
  }

  const report = reportRes?.data
  if (!report) {
    return (
      <div className="flex h-[calc(100vh-64px)] flex-col items-center justify-center">
        <h2 className="text-xl font-semibold text-[#1B3A5C]">Report not found</h2>
        <p className="mt-2 text-[#6B7280]">
          This report may not exist or you may not have access.
        </p>
        <Link
          href="/"
          className="mt-4 text-sm text-[#2563EB] hover:underline"
        >
          Back to home
        </Link>
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100vh-64px)] flex-col">
      {/* Report header bar */}
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link
          href="/"
          className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <h1 className="text-sm font-semibold text-[#1B3A5C]">{report.title}</h1>
        {report.category && (
          <span className="rounded-full bg-[#F3F4F6] px-2 py-0.5 text-xs text-[#6B7280]">
            {report.category}
          </span>
        )}
      </div>

      {/* Qlik embed - full remaining height */}
      <div className="flex-1">
        <QlikEmbed
          appId={report.qlik_app_id}
          sheetId={report.qlik_sheet_id}
        />
      </div>
    </div>
  )
}
