"use client"

import { XrayDfwReportContent } from "@/components/XrayDfwReportContent"
import { ReportGuard } from "@/components/ReportGuard"
export default function XrayDfwPage() {
  return (
    <ReportGuard reportKey="xray-dfw-mng">
      <XrayDfwReportContent apiPrefix="custom/xray-dfw" title="XRay DFW Mng" />
    </ReportGuard>
  )
}
