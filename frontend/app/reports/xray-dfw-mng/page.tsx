"use client"

import { XrayDfwReportContent } from "@/components/XrayDfwReportContent"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"

export default function XrayDfwPage() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["xray-dfw-mng"]]}>
      <XrayDfwReportContent apiPrefix="custom/xray-dfw" title="XRay DFW Mng" />
    </RoleGuard>
  )
}
