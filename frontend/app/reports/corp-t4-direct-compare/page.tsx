"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { DirectCompareContent } from "@/components/DirectCompareContent"

export default function CorpT4DirectComparePage() {
  return (
    <ReportGuard reportKey="corp-t4-direct-compare">
      <DirectCompareContent
        apiPrefix="custom/ops-direct-compare-t4"
        title="CORP T4 Direct Compare"
        lockedTeam="TEAM4"
        badge="CORP · T4"
      />
    </ReportGuard>
  )
}
