"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { OpsPortalOverviewContent } from "@/components/OpsPortalOverviewContent"

export default function CorpT4OpsKamPortalPage() {
  return (
    <ReportGuard reportKey="corp-t4-ops-kam-portal">
      <OpsPortalOverviewContent
        apiPrefix="custom/ops-portal-overview-t4"
        title="CORP T4 OPS Kam Portal"
        lockedTeam="TEAM4"
        badge="CORP · T4"
      />
    </ReportGuard>
  )
}
