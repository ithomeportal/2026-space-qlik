"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { OpsPortalDfwTeamContent } from "@/components/OpsPortalDfwTeamContent"

/** OPS Portal DFW TM1 — the DFW portal locked to TM1 (Bruno 2026-11-09). */
export default function OpsPortalDfwTm1Page() {
  return (
    <ReportGuard reportKey="ops-portal-dfw-tm1">
      <OpsPortalDfwTeamContent tm="TM1" />
    </ReportGuard>
  )
}
