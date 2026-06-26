"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { CustomerScoreContent } from "@/components/CustomerScoreContent"

export default function CorpT1CustomerScorePage() {
  return (
    <ReportGuard reportKey="corp-t1-customer-score">
      <CustomerScoreContent
        apiPrefix="custom/ops-customer-score-t1"
        title="CORP T1 Customer Scorecard"
        lockedTeam="TEAM1"
        badge="CORP · T1"
      />
    </ReportGuard>
  )
}
