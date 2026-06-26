"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { OpsPortalOverviewContent } from "@/components/OpsPortalOverviewContent"

export default function OpsPortalOverviewPage() {
  return (
    <ReportGuard reportKey="ops-portal-overview">
      <OpsPortalOverviewContent />
    </ReportGuard>
  )
}
