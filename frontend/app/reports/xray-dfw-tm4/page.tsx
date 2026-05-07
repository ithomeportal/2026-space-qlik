"use client"

import { XrayDfwReportContent } from "@/components/XrayDfwReportContent"
import { ReportGuard } from "@/components/ReportGuard"
export default function XrayDfwTm4Page() {
  return (
    <ReportGuard reportKey="xray-dfw-tm4">
      <XrayDfwReportContent
        apiPrefix="custom/xray-dfw-tm4"
        title="XRay DFW TM4"
        lockedTeam="TM4"
      />
    </ReportGuard>
  )
}
