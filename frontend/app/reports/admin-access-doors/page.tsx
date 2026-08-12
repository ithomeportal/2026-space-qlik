"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { ScopedAccessDoorsReport } from "@/components/access-doors/ScopedAccessDoorsReport"

/**
 * Admin - Access Log Doors (2026-05-07).
 *
 * Clone of HR - Access Log Doors, server-locked to `dep = 'Admin'`. Migrated
 * 2026-08-12 from a private 382-line page + its own api lib onto the shared
 * factory in `scoped_access_doors.py` / `ScopedAccessDoorsReport`. The emitted
 * SQL was proven identical before the swap — this report's numbers and layout
 * did not change.
 */
export default function AdminAccessDoorsPage() {
  return (
    <ReportGuard reportKey="admin-access-doors">
      <ScopedAccessDoorsReport
        slug="admin-access-doors"
        title="Admin - Access Log Doors"
        scopeLabel="Admin"
      />
    </ReportGuard>
  )
}
