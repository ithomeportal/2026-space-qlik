"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { CustomerScoreContent } from "@/components/CustomerScoreContent"

export default function CorpT4CustomerScorePage() {
  return (
    <ReportGuard reportKey="corp-t4-customer-score">
      <CustomerScoreContent
        apiPrefix="custom/ops-customer-score-t4"
        title="CORP T4 Customer Scorecard"
        lockedTeam="TEAM4"
        badge="CORP · T4"
      />
    </ReportGuard>
  )
}
