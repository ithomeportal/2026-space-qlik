"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { OpsPortalOverviewContent } from "@/components/OpsPortalOverviewContent"

export default function CorpT3OpsKamPortalPage() {
  return (
    <ReportGuard reportKey="corp-t3-ops-kam-portal">
      <OpsPortalOverviewContent
        apiPrefix="custom/ops-portal-overview-t3"
        title="CORP T3 OPS Kam Portal"
        lockedTeam="TEAM3"
        badge="CORP · T3"
      />
    </ReportGuard>
  )
}
