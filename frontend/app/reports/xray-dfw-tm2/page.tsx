"use client"

import { XrayDfwReportContent } from "@/components/XrayDfwReportContent"
import { RoleGuard } from "@/components/RoleGuard"
import { REPORT_ACCESS } from "@/lib/report-access"

export default function XrayDfwTm2Page() {
  return (
    <RoleGuard roles={[...REPORT_ACCESS["xray-dfw-tm2"]]}>
      <XrayDfwReportContent
        apiPrefix="custom/xray-dfw-tm2"
        title="XRay DFW TM2"
        lockedTeam="TM2"
      />
    </RoleGuard>
  )
}
