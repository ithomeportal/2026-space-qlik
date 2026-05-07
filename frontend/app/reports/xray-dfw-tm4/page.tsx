"use client"

import { XrayDfwReportContent } from "@/components/XrayDfwReportContent"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"

export default function XrayDfwTm4Page() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["xray-dfw-tm4"]]}>
      <XrayDfwReportContent
        apiPrefix="custom/xray-dfw-tm4"
        title="XRay DFW TM4"
        lockedTeam="TM4"
      />
    </RoleGuard>
  )
}
