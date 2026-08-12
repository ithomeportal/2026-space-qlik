"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { ScopedAccessDoorsReport } from "@/components/access-doors/ScopedAccessDoorsReport"

/**
 * Pricing - Access Log Doors (Bruno PDF 2026-08-12, Requests 3-4).
 *
 * Clone of HR - Access Log Doors, server-locked to `dep = 'Pricing'`. The
 * Department filter is gone from the UI; the scope is a fixed SQL gate in
 * `backend/app/routers/scoped_access_doors.py` so it can't be widened here.
 */
export default function PricingAccessDoorsPage() {
  return (
    <ReportGuard reportKey="pricing-access-doors">
      <ScopedAccessDoorsReport
        slug="pricing-access-doors"
        title="Pricing - Access Log Doors"
        scopeLabel="Pricing"
      />
    </ReportGuard>
  )
}
