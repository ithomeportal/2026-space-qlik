"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { OpsPortalOverviewContent } from "@/components/OpsPortalOverviewContent"

export default function CorpT2OpsKamPortalPage() {
  return (
    <ReportGuard reportKey="corp-t2-ops-kam-portal">
      <OpsPortalOverviewContent
        apiPrefix="custom/ops-portal-overview-t2"
        title="CORP T2 OPS Kam Portal"
        lockedTeam="TEAM2"
        badge="CORP · T2"
        hideBonusNav
      />
    </ReportGuard>
  )
}
