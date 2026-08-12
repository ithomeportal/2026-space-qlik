"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { ScopedAccessDoorsReport } from "@/components/access-doors/ScopedAccessDoorsReport"

/**
 * OPS - Access Log Doors (Bruno PDF 2026-08-12, Requests 1-2).
 *
 * Clone of HR - Access Log Doors, server-locked to `dep = 'Operations'`. The
 * Department filter is gone from the UI; the scope is a fixed SQL gate in
 * `backend/app/routers/scoped_access_doors.py` so it can't be widened here.
 *
 * Note: `Operations` and `Operations (DFW)` are distinct canonical departments
 * — DFW punches belong to /reports/dfw-access-doors, not this report.
 */
export default function OpsAccessDoorsPage() {
  return (
    <ReportGuard reportKey="ops-access-doors">
      <ScopedAccessDoorsReport
        slug="ops-access-doors"
        title="OPS - Access Log Doors"
        scopeLabel="Operations"
      />
    </ReportGuard>
  )
}
