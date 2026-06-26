"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { DirectCompareContent } from "@/components/DirectCompareContent"

export default function OpsDirectComparePage() {
  return (
    <ReportGuard reportKey="ops-direct-compare">
      <DirectCompareContent />
    </ReportGuard>
  )
}
