"use client"

import { XrayDfwReportContent } from "@/components/XrayDfwReportContent"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"

export default function XrayDfwTm3Page() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["xray-dfw-tm3"]]}>
      <XrayDfwReportContent
        apiPrefix="custom/xray-dfw-tm3"
        title="XRay DFW TM3"
        lockedTeam="TM3"
      />
    </RoleGuard>
  )
}
