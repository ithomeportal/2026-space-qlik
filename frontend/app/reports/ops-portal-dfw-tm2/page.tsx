"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { OpsPortalDfwTeamContent } from "@/components/OpsPortalDfwTeamContent"

/** OPS Portal DFW TM2 — the DFW portal locked to TM2 (Bruno 2026-11-09). */
export default function OpsPortalDfwTm2Page() {
  return (
    <ReportGuard reportKey="ops-portal-dfw-tm2">
      <OpsPortalDfwTeamContent tm="TM2" />
    </ReportGuard>
  )
}
