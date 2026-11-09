"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { OpsPortalDfwTeamContent } from "@/components/OpsPortalDfwTeamContent"

/** OPS Portal DFW TM3 — the DFW portal locked to TM3 (Bruno 2026-11-09). */
export default function OpsPortalDfwTm3Page() {
  return (
    <ReportGuard reportKey="ops-portal-dfw-tm3">
      <OpsPortalDfwTeamContent tm="TM3" />
    </ReportGuard>
  )
}
