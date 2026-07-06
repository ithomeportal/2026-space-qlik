"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { OpsPortalOverviewContent } from "@/components/OpsPortalOverviewContent"

export default function CorpT1OpsKamPortalPage() {
  return (
    <ReportGuard reportKey="corp-t1-ops-kam-portal">
      <OpsPortalOverviewContent
        apiPrefix="custom/ops-portal-overview-t1"
        title="CORP T1 OPS Kam Portal"
        lockedTeam="TEAM1"
        badge="CORP · T1"
        hideBonusNav
      />
    </ReportGuard>
  )
}
