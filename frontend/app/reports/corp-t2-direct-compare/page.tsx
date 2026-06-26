"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { DirectCompareContent } from "@/components/DirectCompareContent"

export default function CorpT2DirectComparePage() {
  return (
    <ReportGuard reportKey="corp-t2-direct-compare">
      <DirectCompareContent
        apiPrefix="custom/ops-direct-compare-t2"
        title="CORP T2 Direct Compare"
        lockedTeam="TEAM2"
        badge="CORP · T2"
      />
    </ReportGuard>
  )
}
