"use client"

import { useEffect } from "react"
import { useParams, useRouter } from "next/navigation"
import { useReport } from "@/lib/api"
import { Skeleton } from "@/components/ui/skeleton"
import Link from "next/link"

export default function ReportViewerPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const { data: reportRes, isLoading } = useReport(id)

  // Every report is now a code-made (custom) report rendered at its own
  // Next.js route — redirect there. (Qlik embedding was removed 2026-05-28.)
  const report = reportRes?.data
  useEffect(() => {
    if (report?.custom_path) {
      router.replace(report.custom_path)
    }
  }, [report, router])

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

  // Custom report with a path — show a lightweight placeholder while the
  // useEffect redirect kicks in.
  if (report.custom_path) {
    return (
      <div className="flex h-[calc(100vh-64px)] items-center justify-center">
        <Skeleton className="h-8 w-64" />
      </div>
    )
  }

  // No embed target (legacy/misconfigured row).
  return (
    <div className="flex h-[calc(100vh-64px)] flex-col items-center justify-center">
      <h2 className="text-xl font-semibold text-[#1B3A5C]">Report unavailable</h2>
      <p className="mt-2 text-[#6B7280]">This report is no longer available.</p>
      <Link href="/" className="mt-4 text-sm text-[#2563EB] hover:underline">
        Back to home
      </Link>
    </div>
  )
}
