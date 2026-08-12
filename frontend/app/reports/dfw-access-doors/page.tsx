"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { ScopedAccessDoorsReport } from "@/components/access-doors/ScopedAccessDoorsReport"

/**
 * DFW - Access Log Doors (2026-04-28).
 *
 * Clone of HR - Access Log Doors, server-locked to `dep = 'Operations (DFW)'`.
 * Migrated 2026-08-12 from a private 382-line page + its own api lib onto the
 * shared factory in `scoped_access_doors.py` / `ScopedAccessDoorsReport`. The
 * emitted SQL was proven identical before the swap — this report's numbers and
 * layout did not change.
 */
export default function DfwAccessDoorsPage() {
  return (
    <ReportGuard reportKey="dfw-access-doors">
      <ScopedAccessDoorsReport
        slug="dfw-access-doors"
        title="DFW - Access Log Doors"
        scopeLabel="Operations (DFW)"
      />
    </ReportGuard>
  )
}
