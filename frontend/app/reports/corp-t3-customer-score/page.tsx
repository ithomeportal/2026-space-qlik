"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { CustomerScoreContent } from "@/components/CustomerScoreContent"

export default function CorpT3CustomerScorePage() {
  return (
    <ReportGuard reportKey="corp-t3-customer-score">
      <CustomerScoreContent
        apiPrefix="custom/ops-customer-score-t3"
        title="CORP T3 Customer Scorecard"
        lockedTeam="TEAM3"
        badge="CORP · T3"
      />
    </ReportGuard>
  )
}
