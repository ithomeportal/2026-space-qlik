"use client"

import { XrayDfwReportContent } from "@/components/XrayDfwReportContent"
import { ReportGuard } from "@/components/ReportGuard"
export default function XrayDfwTm1Page() {
  return (
    <ReportGuard reportKey="xray-dfw-tm1">
      <XrayDfwReportContent
        apiPrefix="custom/xray-dfw-tm1"
        title="XRay DFW TM1"
        lockedTeam="TM1"
      />
    </ReportGuard>
  )
}
