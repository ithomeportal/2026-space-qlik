"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { CustomerScoreContent } from "@/components/CustomerScoreContent"

export default function OpsCustomerScorePage() {
  return (
    <ReportGuard reportKey="ops-customer-score">
      <CustomerScoreContent />
    </ReportGuard>
  )
}
