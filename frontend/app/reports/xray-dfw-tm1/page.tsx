"use client"

import { XrayDfwReportContent } from "@/components/XrayDfwReportContent"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"

export default function XrayDfwTm1Page() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["xray-dfw-tm1"]]}>
      <XrayDfwReportContent
        apiPrefix="custom/xray-dfw-tm1"
        title="XRay DFW TM1"
        lockedTeam="TM1"
      />
    </RoleGuard>
  )
}
