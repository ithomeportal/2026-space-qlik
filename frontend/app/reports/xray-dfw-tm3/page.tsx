"use client"

import { XrayDfwReportContent } from "@/components/XrayDfwReportContent"
import { ReportGuard } from "@/components/ReportGuard"
export default function XrayDfwTm3Page() {
  return (
    <ReportGuard reportKey="xray-dfw-tm3">
      <XrayDfwReportContent
        apiPrefix="custom/xray-dfw-tm3"
        title="XRay DFW TM3"
        lockedTeam="TM3"
      />
    </ReportGuard>
  )
}
