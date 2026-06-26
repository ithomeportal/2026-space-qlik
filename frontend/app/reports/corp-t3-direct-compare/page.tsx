"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { DirectCompareContent } from "@/components/DirectCompareContent"

export default function CorpT3DirectComparePage() {
  return (
    <ReportGuard reportKey="corp-t3-direct-compare">
      <DirectCompareContent
        apiPrefix="custom/ops-direct-compare-t3"
        title="CORP T3 Direct Compare"
        lockedTeam="TEAM3"
        badge="CORP · T3"
      />
    </ReportGuard>
  )
}
