"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { DirectCompareContent } from "@/components/DirectCompareContent"

export default function CorpT1DirectComparePage() {
  return (
    <ReportGuard reportKey="corp-t1-direct-compare">
      <DirectCompareContent
        apiPrefix="custom/ops-direct-compare-t1"
        title="CORP T1 Direct Compare"
        lockedTeam="TEAM1"
        badge="CORP · T1"
      />
    </ReportGuard>
  )
}
