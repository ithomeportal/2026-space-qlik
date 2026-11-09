"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { OpsPortalDfwTeamContent } from "@/components/OpsPortalDfwTeamContent"

/** OPS Portal DFW TM4 — the DFW portal locked to TM4 (Bruno 2026-11-09). */
export default function OpsPortalDfwTm4Page() {
  return (
    <ReportGuard reportKey="ops-portal-dfw-tm4">
      <OpsPortalDfwTeamContent tm="TM4" />
    </ReportGuard>
  )
}
