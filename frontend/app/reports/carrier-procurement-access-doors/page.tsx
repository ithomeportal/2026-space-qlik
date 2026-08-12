"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { ScopedAccessDoorsReport } from "@/components/access-doors/ScopedAccessDoorsReport"

/**
 * Carrier Procurement - Access Log Doors (Bruno PDF 2026-08-12, Requests 5-6).
 *
 * Clone of HR - Access Log Doors, server-locked by JOB TITLE rather than
 * department: `jt IN ('Carrier Procurement','Carrier Procurement Team Leader')`.
 * BOTH the Department and Job Title filters are removed from the UI
 * (`showJobTitleFilter={false}`) — the gate lives in
 * `backend/app/routers/scoped_access_doors.py` and can't be widened here.
 *
 * The by-job-title chart still renders (2 bars, one per gated title): it shows
 * the breakdown, it does not act as a filter.
 */
export default function CarrierProcurementAccessDoorsPage() {
  return (
    <ReportGuard reportKey="carrier-procurement-access-doors">
      <ScopedAccessDoorsReport
        slug="carrier-procurement-access-doors"
        title="Carrier Procurement - Access Log Doors"
        scopeLabel="Carrier Procurement"
        showJobTitleFilter={false}
      />
    </ReportGuard>
  )
}
