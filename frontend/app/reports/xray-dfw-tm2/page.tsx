"use client"

import { XrayDfwReportContent } from "@/components/XrayDfwReportContent"
import { ReportGuard } from "@/components/ReportGuard"
export default function XrayDfwTm2Page() {
  return (
    <ReportGuard reportKey="xray-dfw-tm2">
      <XrayDfwReportContent
        apiPrefix="custom/xray-dfw-tm2"
        title="XRay DFW TM2"
        lockedTeam="TM2"
      />
    </ReportGuard>
  )
}
